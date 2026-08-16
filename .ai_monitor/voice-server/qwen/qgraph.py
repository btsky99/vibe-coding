# -*- coding: utf-8 -*-
"""커널 띄우는 값을 없앤다 — code_predictor 의 15스텝을 **CUDA 그래프 한 장**으로 만든다.

   [왜 이 길인가 — 세 가지를 재고 골랐다]
     ① 계측이 가리키는 것은 계산이 아니라 **띄우는 값**이다.
        배치1 22.1초 vs 배치16 36.9초 — 일이 16배인데 시간은 1.7배. 준비 비용 0%,
        캐시 정상(앞뒤 1.01배). GPU 가 노는데 시간이 가면 남는 답은 하나뿐이다.
     ② torch.compile 은 이 기계에서 못 쓴다. inductor 는 triton 이 있어야 하는데
        `import triton` 이 없다(Windows·py3.12). mode="reduce-overhead" 는 애초에 막혀 있다.
     ③ CUDA 그래프는 **커널을 바꾸지 않는다** — 같은 커널을 같은 순서로 다시 틀 뿐이다.
        그래서 수가 달라질 자리가 없다. 소리가 흔들릴 수 있는 곳은 오직 난수(sampling)인데
        그것은 원래도 부를 때마다 다르다(do_sample=True).

   [무엇을 한 장에 담았나] 프레임 하나마다 도는 이 덩어리 전부:
     code_predictor 프리필(2칸) → 14번의 한 칸씩 → 15개 코드 뽑기 → 그 코드들의 임베딩 합.
     예전에는 이 안에서 HF generate 가 15번 돌며 커널을 하나씩 띄웠다. 이제 replay 한 번이다.

   [되돌리는 법] `VOICE_QWEN_GRAPH=0` 으로 띄우면 이 파일은 아예 손대지 않는다
     (z_qwen_worker 가 install() 을 건너뛴다). 파일을 지울 필요도 없다.
"""
import os

import torch

# [🔴 끄는 값만 정해 둔다] 전에는 켜는 값 목록("1","on"…)만 인정했다. 그래서
#   VOICE_QWEN_GRAPH=cp (code_predictor 만) 로 두면 **켠 줄 알고 꺼지는** 자리가 있었다.
#   이제는 "꺼라"라고 적은 것만 끈다 — 나머지는 모드 이름으로 본다.
_OFF = ("0", "false", "no", "off", "")


def enabled():
    return os.environ.get("VOICE_QWEN_GRAPH", "cp").lower() not in _OFF


class _Result:
    """HF generate 의 반환을 흉내낸다 — 부르는 쪽(talker.forward)이 `.sequences` 만 본다."""

    __slots__ = ("sequences",)

    def __init__(self, sequences):
        self.sequences = sequences


class CodePredictorGraph:
    """batch 크기마다 그래프를 한 장씩 만들어 둔다(모양이 고정이어야 그래프가 된다)."""

    def __init__(self, cp, top_k=50, temperature=0.9, do_sample=True):
        self.cp = cp
        self.model = cp.model
        self.embeds = cp.get_input_embeddings()      # 15개 nn.Embedding
        self.heads = cp.lm_head                      # 15개 nn.Linear
        self.proj = cp.small_to_mtp_projection       # 폭이 같으면 Identity
        self.G = int(cp.config.num_code_groups)      # 16
        self.n_new = self.G - 1                      # 15
        self.top_k = int(top_k)
        self.temperature = float(temperature)
        self.do_sample = bool(do_sample)
        self.device = next(cp.parameters()).device
        self.dtype = next(cp.parameters()).dtype
        self.graphs = {}                             # batch -> (정적 입력, 정적 출력, 그래프)
        self.mempool = None

    # ── 손으로 쓴 15스텝 — HF generate 가 하던 일을 그대로, 파이썬 군더더기 없이 ──────
    def _loop(self, embeds_in, _unused=None):
        """embeds_in: (B, 2, H) = (past_hidden, last_id_hidden).
        반환: 코드 15개 (B,15) 와 그 임베딩 합 (B,1,H).

        [HF 와 똑같이 가야 하는 자리]
          · 프리필은 2칸을 넣고 lm_head[0] 으로 첫 코드를 뽑는다(cp.forward 의 generation_steps=0).
          · k번째 스텝(k=1..14)은 codec_embedding[k-1] 로 들어가 lm_head[k] 로 나온다.
          · 로짓 처리 순서: temperature → top_k → softmax → multinomial (top_p=1.0 은 HF 도 건너뛴다).

        [🔴 StaticCache 를 쓰지 않는다 — 실측으로 배웠다] 처음엔 고정 길이 캐시를 썼는데
          greedy 코드 210개 중 41개가 HF 와 어긋났다. 아직 안 채운 칸까지 어텐션이
          들여다본 것이다(mask 를 안 받으면 sdpa 가 is_causal 로 흘려버린다).
          **DynamicCache 를 그래프 안에서 그대로 쓴다** — 15스텝을 통째로 잡아 두면
          cat 이 만드는 자리가 replay 마다 같으므로 그래프가 성립하고, 수는 HF 와 한 자리도
          다르지 않다."""
        from transformers import DynamicCache
        cache = DynamicCache()
        pos = torch.arange(2, device=self.device)
        h = self.proj(embeds_in)
        out = self.model(input_ids=None, attention_mask=None, position_ids=None,
                         past_key_values=cache, inputs_embeds=h, use_cache=True,
                         cache_position=pos)
        hidden = out.last_hidden_state[:, -1]                     # (B,H)

        toks, embs = [], []
        for k in range(self.n_new):
            logits = self.heads[k](hidden).float()                # (B,V)
            tok = self._pick(logits)                              # (B,1)
            toks.append(tok)
            e = self.embeds[k](tok)                               # (B,1,H_talker)
            embs.append(e)
            if k == self.n_new - 1:
                break
            cpos = torch.arange(2 + k, 3 + k, device=self.device)
            out = self.model(input_ids=None, attention_mask=None, position_ids=None,
                             past_key_values=cache, inputs_embeds=self.proj(e),
                             use_cache=True, cache_position=cpos)
            hidden = out.last_hidden_state[:, -1]
        return torch.cat(toks, dim=1), torch.cat(embs, dim=1).sum(1, keepdim=True), None

    def _pick(self, logits):
        """HF 의 로짓 처리를 그대로 옮긴 것 — 순서도 연산도 같다.
        (Temperature → TopK(-inf 채우기) → softmax → multinomial. top_p=1.0 은 HF 도 건너뛴다.)
        multinomial 이 그래프 안에서 잡히고 replay 마다 새 난수를 뽑는 것은 실측으로 확인했다."""
        if not self.do_sample:
            return logits.argmax(-1, keepdim=True)
        logits = logits / self.temperature
        kth = torch.topk(logits, self.top_k, dim=-1)[0][..., -1, None]
        logits = logits.masked_fill(logits < kth, float("-inf"))
        probs = torch.softmax(logits, dim=-1)
        return torch.multinomial(probs, num_samples=1)

    # ── 그래프 만들고 쓰기 ────────────────────────────────────────────────────
    def _build(self, B):
        H = self.cp.config.hidden_size
        static_in = torch.zeros(B, 2, H, device=self.device, dtype=self.dtype)

        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):                          # 예열 3판 — 그래프 밖에서
            for _ in range(3):
                self._loop(static_in)
        torch.cuda.current_stream().wait_stream(s)
        torch.cuda.synchronize()

        g = torch.cuda.CUDAGraph()
        if self.mempool is None:
            with torch.cuda.graph(g):
                tok, emb, _ = self._loop(static_in)
            self.mempool = g.pool()
        else:
            with torch.cuda.graph(g, pool=self.mempool):
                tok, emb, _ = self._loop(static_in)
        self.graphs[B] = (static_in, tok, emb, g)
        return self.graphs[B]

    @torch.no_grad()
    def run(self, embeds_in):
        B = embeds_in.shape[0]
        ent = self.graphs.get(B) or self._build(B)
        static_in, tok, emb, g = ent
        static_in.copy_(embeds_in)
        g.replay()
        return tok, emb


class _Shim:
    """HF generate 의 반환 중 부르는 쪽이 실제로 들여다보는 것만 흉내낸다.
    (Qwen3TTSForConditionalGeneration.generate 가 hid[0][-1][:, -1:] 와 hid[-1] 만 본다.)"""

    __slots__ = ("hidden_states",)

    def __init__(self, hidden_states):
        self.hidden_states = hidden_states


class TalkerGraph:
    """프레임 하나를 통째로 그래프 한 장에 담는다 — code_predictor 15스텝 + talker 28층 + 뽑기.

       [왜 여기까지 오나] code_predictor 만 묶었을 때 프레임당 394ms → 140ms 였다.
         남은 140ms 의 대부분은 talker 28층을 커널 하나씩 띄우는 값이다. 층이 5개인
         code_predictor 가 15스텝에 25ms 였으니 28층 한 스텝이 100ms 를 먹을 이유는 계산이 아니다.

       [무엇을 손으로 다시 썼나] HF generate 의 한 스텝을 그대로 옮겼다 — 순서까지 같게:
         반복벌(1.05) → eos 막기(min_new_tokens=2) → 금지토큰 → 온도(0.9) → top_k(50)
         → softmax → multinomial. top_p=1.0 은 HF 도 건너뛴다.
         맞는지는 짐작이 아니라 **greedy 로 통짜 문장을 구워 코드가 한 자도 안 틀리는지**로 본다.

       [🔴 고정 길이 캐시라 mask 를 내가 만든다] 아직 안 채운 칸을 어텐션이 보면 안 된다.
         code_predictor 에서 이 자리를 놓쳐 210개 중 41개가 어긋났었다. 여기서는
         create_causal_mask 를 아예 안 거치고 4차원 mask 를 직접 만들어 층에 넣는다."""

    def __init__(self, model, cp_engine, cap_frames=384, bucket=128, check_every=4):
        self.m = model
        self.talker = model.model.talker
        self.tk = self.talker
        self.cfg = self.talker.config
        self.cp = cp_engine
        self.cap = int(os.environ.get("VOICE_QWEN_CAPFRAMES", cap_frames))
        self.bucket = bucket
        self.check_every = int(os.environ.get("VOICE_QWEN_EOSCHECK", check_every))
        self.device = next(self.talker.parameters()).device
        self.dtype = next(self.talker.parameters()).dtype
        self.V = int(self.cfg.vocab_size)
        self.H = int(self.cfg.hidden_size)
        self.eos = int(self.cfg.codec_eos_token_id)
        self.states = {}
        self.mempool = None
        self.stats = {"capture": 0, "capture_s": 0.0, "calls": 0, "hit_cap": 0}

    # ── 정적 자리 만들기 ──────────────────────────────────────────────────────
    def _state(self, B, L, gk):
        # [🔴 뽑는 방식이 바뀌면 그래프도 새로 뜬다] 그래프는 구운 그대로 다시 틀 뿐이라,
        #   greedy 로 뜬 그래프에 sampling 을 시킬 수 없다.
        key = (B, L, bool(gk.get("do_sample", True)), bool(self.cp.do_sample))
        st = self.states.get(key)
        if st is not None:
            return st
        from transformers import StaticCache
        dev, dt = self.device, self.dtype
        try:
            cache = StaticCache(config=self.cfg, max_batch_size=B, max_cache_len=L,
                                device=dev, dtype=dt)
        except TypeError:
            cache = StaticCache(config=self.cfg, batch_size=B, max_cache_len=L,
                                device=dev, dtype=dt)
        neg = torch.finfo(dt).min          # HF 도 -inf 가 아니라 이 값을 쓴다(NaN 방지)
        sup = torch.zeros(self.V, device=dev, dtype=torch.float32)
        for i in range(self.V - 1024, self.V):
            if i != self.eos:
                sup[i] = float("-inf")
        st = {
            "cache": cache, "L": L, "B": B, "neg": neg,
            "pad_mask": torch.ones(B, L, device=dev, dtype=torch.bool),
            "cur": torch.zeros(1, device=dev, dtype=torch.long),
            "step": torch.zeros(1, device=dev, dtype=torch.long),
            "rope_d": torch.zeros(B, 1, device=dev, dtype=torch.float32),
            "past_hidden": torch.zeros(B, 1, self.H, device=dev, dtype=dt),
            "last_tok": torch.zeros(B, 1, device=dev, dtype=torch.long),
            "seen": torch.zeros(B, self.V, device=dev, dtype=torch.bool),
            "unfin": torch.ones(B, 1, device=dev, dtype=torch.long),
            "suppress": sup,
            "eos_block": torch.zeros(self.V, device=dev, dtype=torch.float32),
            "trail": torch.zeros(B, self.cap + 2, self.H, device=dev, dtype=dt),
            "codes": torch.zeros(B, self.cap, 16, device=dev, dtype=torch.long),
            "hid": torch.zeros(B, self.cap, self.H, device=dev, dtype=dt),
            "graph": None,
        }
        st["eos_block"][self.eos] = float("-inf")
        self.states[key] = st
        return st

    # ── 층 통과(프리필·디코드 공용) — create_causal_mask 를 거치지 않는다 ─────────
    def _layers(self, h, mask4d, pos_ids, cache_pos, cache):
        tk = self.tk
        cos, sin = tk.model.rotary_emb(h, pos_ids)
        text_pos = pos_ids[0]
        for layer in tk.model.layers:
            h = layer(h, attention_mask=mask4d, position_ids=text_pos,
                      past_key_values=cache, use_cache=True, cache_position=cache_pos,
                      position_embeddings=(cos, sin))[0]
        return tk.model.norm(h)

    def _sample(self, logits, st, gk):
        """HF 의 로짓 처리기를 순서까지 그대로. logits: (B,V) float32."""
        p = float(gk["repetition_penalty"])
        if p != 1.0:
            logits = torch.where(st["seen"],
                                 torch.where(logits < 0, logits * p, logits / p),
                                 logits)
        logits = logits + st["eos_block"] + st["suppress"]
        if not gk.get("do_sample", True):
            # HF 는 do_sample=False 면 온도·top_k 를 아예 달지 않는다 — 그대로 맞춘다
            return logits.argmax(-1, keepdim=True)
        logits = logits / float(gk["temperature"])
        k = int(gk["top_k"])
        if k and k < self.V:
            kth = torch.topk(logits, k, dim=-1)[0][..., -1, None]
            logits = logits.masked_fill(logits < kth, float("-inf"))
        return torch.multinomial(torch.softmax(logits, dim=-1), num_samples=1)

    # ── 프레임 한 장 = 그래프에 담길 몸통 ────────────────────────────────────────
    def _frame(self, st, gk):
        tk, cache, L = self.tk, st["cache"], st["L"]
        last_id_hidden = tk.get_input_embeddings()(st["last_tok"])            # (B,1,H)
        tok15, embsum, _ = self.cp._loop(                                     # noqa: SLF001
            torch.cat((st["past_hidden"], last_id_hidden), dim=1))
        codec_ids = torch.cat((st["last_tok"], tok15), dim=-1)                # (B,16)
        emb = last_id_hidden + embsum
        emb = emb + st["trail"].index_select(1, st["step"])                   # (B,1,H)

        cur = st["cur"]
        pos = torch.arange(1, device=self.device).view(1, -1).expand(st["B"], -1)
        pos = pos.add(cur[0] + st["rope_d"]).unsqueeze(0).expand(3, -1, -1)
        valid = st["pad_mask"] & (torch.arange(L, device=self.device).view(1, L) <= cur[0])
        mask4d = torch.where(valid, 0.0, st["neg"]).to(self.dtype).view(st["B"], 1, 1, L)

        h = self._layers(emb, mask4d, pos, cur, cache)                        # (B,1,H)
        logits = tk.codec_head(h)[:, -1].float()                              # (B,V)
        tau = self._sample(logits, st, gk)                                    # (B,1)
        tau = torch.where(st["unfin"].bool(), tau, torch.full_like(tau, self.eos))
        st["unfin"].mul_((tau != self.eos).long())
        st["seen"].scatter_(1, tau, True)

        st["codes"].index_copy_(1, st["step"], codec_ids.unsqueeze(1))
        st["hid"].index_copy_(1, st["step"], h)
        st["past_hidden"].copy_(h)
        st["last_tok"].copy_(tau)
        cur.add_(1)
        st["step"].add_(1)

    def _capture(self, st, gk):
        import time as _t
        t0 = _t.perf_counter()
        snap = {k: st[k].clone() for k in ("cur", "step", "past_hidden", "last_tok",
                                           "seen", "unfin")}
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(3):
                self._frame(st, gk)
        torch.cuda.current_stream().wait_stream(s)
        torch.cuda.synchronize()
        for k, v in snap.items():
            st[k].copy_(v)
        g = torch.cuda.CUDAGraph()
        if self.mempool is None:
            with torch.cuda.graph(g):
                self._frame(st, gk)
            self.mempool = g.pool()
        else:
            with torch.cuda.graph(g, pool=self.mempool):
                self._frame(st, gk)
        for k, v in snap.items():
            st[k].copy_(v)
        st["graph"] = g
        self.stats["capture"] += 1
        self.stats["capture_s"] += _t.perf_counter() - t0

    # ── 바깥에서 부르는 자리 ─────────────────────────────────────────────────────
    @torch.no_grad()
    def generate(self, inputs_embeds=None, attention_mask=None, trailing_text_hidden=None,
                 tts_pad_embed=None, use_graph=True, **kw):
        tk = self.tk
        gk = {"repetition_penalty": kw.get("repetition_penalty", 1.05),
              "temperature": kw.get("temperature", 0.9),
              "top_k": kw.get("top_k", 50),
              "do_sample": kw.get("do_sample", True)}
        self.cp.do_sample = bool(kw.get("subtalker_dosample", True))
        B, P, _ = inputs_embeds.shape
        cap = min(self.cap, int(kw.get("max_new_tokens", 2048)))
        L = int((P + cap + self.bucket - 1) // self.bucket) * self.bucket
        st = self._state(B, L, gk)
        cache, dev = st["cache"], self.device
        cache.reset()
        self.stats["calls"] += 1

        # ① 자리표 — 왼쪽 채움 칸은 영영 가리고, 아직 안 쓴 칸은 그때그때 열린다
        st["pad_mask"].fill_(True)
        st["pad_mask"][:, :P] = attention_mask.bool()
        st["seen"].zero_()
        st["unfin"].fill_(1)
        st["eos_block"][self.eos] = float("-inf")          # min_new_tokens=2 → 처음엔 막는다
        st["codes"].zero_()

        # ② 딸림 텍스트를 고정 자리에 옮긴다(넘치는 뒤쪽은 tts_pad 로 채워 둔다 — 원본과 같다)
        st["trail"].copy_(tts_pad_embed.expand(B, st["trail"].shape[1], -1))
        tt = min(trailing_text_hidden.shape[1], st["trail"].shape[1])
        st["trail"][:, :tt] = trailing_text_hidden[:, :tt]

        # ③ 프리필 — 길이가 부를 때마다 달라서 그래프로 묶지 않는다(한 번뿐이라 값도 싸다)
        pos_ids, rope_d = tk.get_rope_index(attention_mask)
        rope_d = rope_d - (1 - attention_mask).sum(dim=-1).unsqueeze(1)
        tk.rope_deltas = rope_d
        st["rope_d"].copy_(rope_d.float())
        cpos = torch.arange(P, device=dev)
        col = torch.arange(L, device=dev).view(1, 1, 1, L)
        row = cpos.view(1, 1, P, 1)
        valid = (col <= row) & st["pad_mask"].view(B, 1, 1, L)
        mask4d = torch.where(valid, 0.0, st["neg"]).to(self.dtype)
        h = self._layers(inputs_embeds, mask4d, pos_ids, cpos, cache)
        st["past_hidden"].copy_(h[:, -1:])
        st["cur"].fill_(P)
        st["step"].zero_()
        tau = self._sample(tk.codec_head(h)[:, -1].float(), st, gk)
        st["seen"].scatter_(1, tau, True)
        st["last_tok"].copy_(tau)
        prefill_hidden = h[:, -1:].clone()

        # ④ 프레임 굽기 — 한 장에 replay 한 번
        if use_graph and st["graph"] is None:
            self._capture(st, gk)
        T = 0
        for t in range(cap):
            if use_graph:
                st["graph"].replay()
            else:
                self._frame(st, gk)
            T = t + 1
            if t == 0:
                st["eos_block"][self.eos] = 0.0            # min_new_tokens=2 는 여기서 풀린다
            if (t + 1) % self.check_every == 0 and int(st["unfin"].sum()) == 0:
                break
        if T >= cap:
            self.stats["hit_cap"] += 1

        codes, hid = st["codes"][:, :T], st["hid"][:, :T]
        hs = [([prefill_hidden], None)]
        hs += [([hid[:, i:i + 1]], codes[:, i]) for i in range(T)]
        return _Shim(hs)


def install(model, verbose=True, mode=None):
    """talker.forward 안의 `code_predictor.generate` 와 그 뒤 임베딩 합치기를 그래프로 갈아끼운다.

    [무엇을 어디까지 바꾸나] 라이브러리 파일은 건드리지 않는다. 살아 있는 객체의
      메서드만 바꾼다. 프로세스가 끝나면 흔적이 없다.

    [mode] "cp" 면 code_predictor 만. 그 밖의 값이면 talker 28층까지 한 장에 담는다.
      안 주면 VOICE_QWEN_GRAPH 를 본다. **실서비스는 "cp" 다.**

      [🔴 talker 를 켜지 마라 — 자리가 아니라 수가 틀린다 (2026-08-16 23:5x 실측)]
      20:21 의 CUDA OOM 은 검사 스크립트 천장(AB_FRACTION 0.30 = 3.60GiB) 탓이었다.
      0.55 로 올려 다시 재니 안 터졌다. 그런데 **답이 틀렸다**:
        옛 길 46프레임 / 내 루프 384(상한) / 그래프 384 — 어긋남 eager 6061, graph 6061.
      eager 와 graph 가 똑같이 틀렸다 = **그래프가 아니라 TalkerGraph 의 멈춤 판정이 틀렸다.**
      말을 안 멈춘다 — 켜면 사장이 듣는 것은 끝나지 않는 낭독이다.
      속도 값어치는 있다(프레임당 397ms → 30.5ms, 13배). 고친 뒤에 다시 본다.
      근거: bench/talker_check_2026-08-16.txt"""
    talker = model.model.talker if hasattr(model, "model") else model.talker
    cp = talker.code_predictor
    if getattr(cp, "_qgraph", None) is not None:
        return cp._qgraph                                                    # noqa: SLF001

    gk = model._merge_generate_kwargs()                                      # noqa: SLF001
    eng = CodePredictorGraph(cp, top_k=gk.get("subtalker_top_k", 50),
                             temperature=gk.get("subtalker_temperature", 0.9),
                             do_sample=gk.get("subtalker_dosample", True))
    cp._qgraph = eng                                                         # noqa: SLF001

    orig_generate = cp.generate

    def graphed_generate(inputs_embeds=None, **kw):
        # 프리필 2칸이 아닌 부름은 원래 길로 보낸다(있을 리 없지만, 깨지느니 느린 편이 낫다).
        if inputs_embeds is None or inputs_embeds.shape[1] != 2:
            return orig_generate(inputs_embeds=inputs_embeds, **kw)
        tok, emb = eng.run(inputs_embeds)
        r = _Result(tok)
        r.sequences = tok
        eng.last_embed_sum = emb
        return r

    cp.generate = graphed_generate
    cp._qgraph_restore = orig_generate                                       # noqa: SLF001

    mode = str(mode or os.environ.get("VOICE_QWEN_GRAPH", "1")).lower()
    if mode not in ("cp",):
        # 프레임 통째로 — talker 28층까지 같은 그래프에 담는다
        tg = TalkerGraph(model, eng)
        talker._qgraph_talker_restore = talker.generate                      # noqa: SLF001
        talker.generate = tg.generate
        talker._qgraph_talker = tg                                           # noqa: SLF001
        if verbose:
            print("[qgraph] 프레임 한 장 = code_predictor 15스텝 + talker 28층 (그래프 한 장)",
                  flush=True)
    elif verbose:
        print("[qgraph] code_predictor 15스텝을 CUDA 그래프로 묶었다", flush=True)
    return eng


def uninstall(model):
    talker = model.model.talker if hasattr(model, "model") else model.talker
    cp = talker.code_predictor
    if getattr(talker, "_qgraph_talker_restore", None) is not None:
        talker.generate = talker._qgraph_talker_restore                      # noqa: SLF001
        talker._qgraph_talker_restore = None                                 # noqa: SLF001
        talker._qgraph_talker = None                                         # noqa: SLF001
    if getattr(cp, "_qgraph_restore", None) is not None:
        cp.generate = cp._qgraph_restore                                     # noqa: SLF001
        cp._qgraph = None                                                    # noqa: SLF001
        cp._qgraph_restore = None                                            # noqa: SLF001
