# -*- coding: utf-8 -*-
"""상주 일꾼 — 모델을 한 번만 올려 두고 문장을 받아 굽는다.

   [왜 상주인가] 한 문장 부를 때마다 프로세스를 새로 띄우면 import 30초 + 모델 올림 8~21초가
   매번 붙어 61초가 된다. 모델을 물고 있으면 12~17초다. 사장 지시로 그 대가(GPU 2.2GB 상주)를
   알고 붙인다.

   [🔴 학습이 이긴다] 굽기 전마다 nvidia-smi 로 실여유를 본다. 1GB 밑이면 굽지 않고
   'busy' 를 돌려준다. 부모(tts_qwen)가 그때 나를 내려서 2.2GB 를 학습에 돌려준다.
   내 몫에도 25% 천장을 씌운다 — 넘치면 학습이 아니라 내가 죽어야 한다.

   [말 거는 법] 한 줄에 JSON 하나(stdin) → 한 줄에 JSON 하나(stdout).
     {"cmd":"say","text":"...","out":"C:\\...\\a.wav"}  → {"ok":true,"sec":12.7,"dur":2.1}
     {"cmd":"ping"}                                      → {"ok":true,"ready":true}
     {"cmd":"quit"}                                      → 종료
   [🔴 오디오를 stdout 으로 흘리지 않는다] 이 저장소는 stdout=PIPE 를 안 읽어 자식이 멈춘
   사고를 두 번 겪었다. 큰 바이트를 파이프에 실으면 같은 자리로 돌아간다. 파일로 주고,
   파이프에는 짧은 한 줄만 흘린다."""
import json
import os
import subprocess
import sys
import time

# [🔴 이 파일은 보드(G:\apix-voice2\work\z_qwen_worker.py)에서 가져온 사본이다 —
#   2026-08-17 이식]
#   [🔴 원본과 갈라진 자리는 딱 둘이다 — 고칠 때 여기를 먼저 볼 것]
#     ① 경로 기본값(HF_HOME·REF_WAV·REF_JSON) — 보드는 G: 에 고정된 자리를 쓰지만
#        설치본이 깔리는 PC 에는 그 드라이브가 없다. 기본값을 **이 파일 옆**으로 돌렸다.
#     ② 맨 끝의 `del model` → `model = None` — 이유는 그 자리 주석 참조(린트가 빌드를 깬다).
#   그 밖의 로직(그래프 꽂기·묶어 굽기·say_parts 규약)은 원본과 같아야 한다 —
#   어긋나면 보드에서 잰 숫자가 여기서 거짓말이 된다.
HERE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["HF_HOME"] = os.environ.get(
    "HF_HOME", os.path.join(HERE_DIR, "models", "hf"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ.pop("HF_HUB_OFFLINE", None)

MODEL_ID = os.environ.get("VOICE_QWEN_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
# [🔴 사장이 고르신 파일이 정본이다 — 2026-08-15 19:52 판] 원문(ref_text)은 받아쓰기가
#   아니라 **파일 이름**에서 왔다 — 사람이 적어 둔 것이라 그 편이 정확하다(받아쓰기는
#   한글을 다 흘렸다). 원본 mp3 는 Downloads 에 그대로 두고 ref/ 로 복사만 했다.
#   되돌리려면 이 줄과 아래 REF_KEY 를 ref_merged / "ref_merged" 로 되돌리면 된다.
#   [🔴 2026-08-16 16:5x 되돌림] 서버 등록에는 여전히 옛 참조(25.7초)가 적혀 있어 PC 와
#   서버의 열쇠가 어긋났다 — 그 사이 사장은 무음이셨다. **소리가 먼저다.**
#   서버가 ref 를 받는 것이 확인되면 boss_pick.wav 로 다시 올린다.
#   [🔴 2026-08-16 23:4x 다시 올린다] 그 조건이 채워졌다 — 서버가 ref 를 받아 적는다
#   (서버 커밋 dc6a68c5, /run/apix/qwen-tts.json 에 "ref": "ead7ae77…" 실물 확인).
#   무음의 원인은 참조 파일이 아니라 **서버가 지문을 버리던 것**이었다. 이제 참조를
#   바꾸면 열쇠가 따라 바뀐다. **ag_bake_now.py 의 REF_WAV 와 함께 바꿔야 한다** —
#   둘이 어긋나면 서버는 A 로 열쇠를 만들고 PC 는 B 로 구워 그것이 곧 무음이다.
#   되돌리려면 이 두 줄을 ref_merged / "ref_merged" 로, ag_bake_now.py:276 도 함께.
#   [🔴 참조가 빠지면 목소리가 달라진다] 이 둘은 설치본에 **반드시 함께 실려야 한다**
#     (vibe-coding.spec datas 의 'voice-server/qwen' 항목과 한 쌍). 모델만 받아 오고
#     참조를 빠뜨리면 소리는 나는데 사장님 목소리가 아니다 — 그것도 '빼먹은 것'이다.
REF_WAV = os.environ.get("VOICE_QWEN_REF", os.path.join(HERE_DIR, "boss_pick.wav"))
REF_JSON = os.environ.get("VOICE_QWEN_REF_TEXT",
                          os.path.join(HERE_DIR, "ref_text.json"))
REF_KEY = os.environ.get("VOICE_QWEN_REF_KEY", "boss_pick")
FLOOR_MB = int(os.environ.get("VOICE_QWEN_FLOOR_MB", "1024"))


# [🔴 stdout 은 내 것이 아니다] qwen_tts 가 뜰 때 배너("****", flash-attn 안내)를 stdout 에
# 찍는다. 그것을 부모가 내 답으로 읽고 '알 수 없는 응답'으로 판정해 나를 죽였다(실측).
# 그래서 내 줄에는 표식을 붙이고, 부모는 표식 있는 줄만 읽는다.
MARK = "@@Q@@"

try:                                     # 한글이 섞여도 파이프에서 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def out(obj):
    try:
        sys.stdout.write(MARK + json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except OSError:
        # 부모가 파이프를 닫았다. 더 쓸 곳이 없으니 조용히 끝낸다.
        raise SystemExit(0)


# [🔴 nvidia-smi 를 부르지 않는다 — 2026-08-16 사장 지시] 전에는 굽기마다 두 번씩 불러
#   여유를 캤다. 그 시간이 곧 사장이 기다리시는 시간이었고(요청→소리 14분 중 11분이 대기),
#   콘솔 없는 부모 밑에서는 부를 때마다 검은 창이 번쩍였다.
#   **구울 수 있는지는 구워 봐야 안다** — 모자라면 그 자리에서 터지고, 터지면 부모가
#   나를 내려 GPU 를 학습에 돌려준 뒤 다음 쪽지에 다시 띄운다.
#   자리를 볼 일이 있으면 torch 에게 묻는다(프로세스를 안 띄우니 창도 없고 공짜다).
def gpu_free_mb():
    try:
        import torch
        return torch.cuda.mem_get_info(0)[0] // (1 << 20)
    except Exception:
        return -1


def main():
    # [🔴 뜨기 전에 여유를 재지 않는다] 자리가 없으면 아래 적재에서 터진다. 그때 부모가
    #   안다. 미리 재면 그 시간이 사장이 기다리시는 시간에 그대로 얹힌다.
    import numpy as np
    import torch
    import soundfile as sf
    from qwen_tts import Qwen3TTSModel

    # [🔴 천장은 고정이다] 전에는 뜨는 순간의 실여유로 천장을 잡았는데, 그때 GPU 가
    #   잠깐 붐비면 천장이 1.7GB 로 잡혀 모델조차 못 올렸다(실측). 고정 천장이면
    #   nvidia-smi 도 필요 없고, **자리가 모자랄 때 학습이 아니라 내가 먼저 터진다** —
    #   그것이 이 저장소가 뜻한 '학습이 이긴다' 다.
    # [🔴 예산이 풀렸다 — 2026-08-16] 학습을 세워 12GB 가 거의 비었다. 2.3GB 는 학습과
    #   나눠 쓸 때 정한 값이었다. 0.55 = 6.8GB 로 올린다 — 묶어 굽기가 자리를 쓰기 때문이다
    #   (배치 16 봉우리 3.4GB 실측). 다만 **다 먹지는 않는다**: 같은 GPU 에서 다른 창이
    #   다른 엔진을 재고 있어 8GB 안쪽에 머문다. 학습이 돌아오면 이 값을 되돌린다.
    # [🔴 학습 몫을 남겨 두지 않는다 — 2026-08-16 23:5x 사장 지시] "학습보다 qwen 이 우선.
    #   무조건 우선." 학습은 17:03 에 세워져 있다. 0.55(6.6GB)는 나눠 쓰던 때 값이다.
    #   0.80 = 9.8GB 로 올린다. **천장이지 예약이 아니다** — 실제로는 지금도 2.2GB 만 쓴다.
    #   학습이 돌아오면 매니저 지시로 되돌린다(VOICE_QWEN_FRACTION 으로 그 자리에서도 된다).
    torch.cuda.set_per_process_memory_fraction(
        float(os.environ.get("VOICE_QWEN_FRACTION", "0.80")), 0)
    ref_text = json.load(open(REF_JSON, encoding="utf-8"))[REF_KEY]
    t0 = time.time()
    model = Qwen3TTSModel.from_pretrained(MODEL_ID, device_map="cuda:0",
                                          dtype=torch.bfloat16,
                                          # [🔴 flash_attention_2 대신 sdpa — 2026-08-16]
                                          #   문서는 flash_attention_2 를 권하지만 그 패키지는
                                          #   이 조합(Windows·py3.12·torch 2.13+cu130)에 미리
                                          #   만들어진 판이 없다(pip 에 아예 후보 0개). 소스에서
                                          #   빌드하면 몇 시간이고 윈도 지원도 부실하다.
                                          #   대신 **PyTorch 의 sdpa 가 같은 FlashAttention
                                          #   커널을 품고 있고**(flash_sdp_enabled=True, SM 8.6)
                                          #   설치가 필요 없다. 실측 이득은 작다 —
                                          #   b1 RTF 6.14(eager) → 5.62~5.91(sdpa), 5~8%.
                                          #   병목은 어텐션이 아니라 커널 띄우는 값이기 때문이다.
                                          attn_implementation=os.environ.get(
                                              "VOICE_QWEN_ATTN", "sdpa"))
    # 참조를 한 번만 인코딩해 둔다(실측 1.71초 → 두 번째부터 0.31초). 묶어 굽기가
    # 이 프롬프트를 그대로 여러 번 쓴다.
    prompt = model.create_voice_clone_prompt(ref_audio=REF_WAV, ref_text=ref_text)

    # ── [🔴 커널 띄우는 값을 없앤다 — qgraph 를 꽂는 자리] ──────────────────────────
    #   [왜] 병목은 계산이 아니라 **프레임마다 code_predictor.generate 를 15번 다시 부르는
    #     것**이었다(배치1 22.1초 vs 배치16 36.9초 — 일 16배에 시간 1.7배). 그 15스텝을
    #     CUDA 그래프 한 장으로 묶으면 replay 한 번이 된다.
    #   [근거·실측] work/bench/graph_probe.json — greedy 코드 210개 중 어긋남 0,
    #     15스텝 277.5ms → 29.7ms(9.4배). work/bench/ab.json — 통짜 굽기 RTF
    #     b1 5.06 → 1.89(2.7배), b6 1.089 → 0.605(2.1배).
    #   [왜 cp 만 — 자리가 아니라 수가 틀려서다] 20:21 의 OOM 은 검사 천장(3.60GiB) 탓이라
    #     23:5x 에 6.6GiB 로 올려 다시 쟀다. 안 터졌다. 그런데 **답이 틀렸다** —
    #     옛 길 46프레임인데 talker 그래프는 384(상한)까지 가고 코드 6061개가 어긋났다.
    #     그래프 없이 돌린 같은 루프도 똑같이 틀렸다 = 멈춤 판정이 틀린 것이다.
    #     켜면 끝나지 않는 낭독이 나간다. bench/talker_check_2026-08-16.txt.
    #   [되돌리는 길 — 둘 다 산다]
    #     ① 환경변수  VOICE_QWEN_GRAPH=0  으로 부모를 띄우면 옛 길.
    #     ② 파일  G:\apix-voice2\work\graph.off  를 만들어 두고 일꾼을 내리면 옛 길.
    #        (부모 환경을 못 만질 때 쓴다 — 부모가 다음 쪽지에 나를 다시 띄운다.)
    #     꽂다가 무슨 일이 나도 옛 길로 굽는다 — 아래 except 가 그 자리다.
    graph_mode = os.environ.get("VOICE_QWEN_GRAPH", "cp").lower()
    HERE = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(HERE, "graph.off")):
        graph_mode = "0"
    graph_on = "off"
    if graph_mode not in ("0", "false", "no", "off", ""):
        try:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import qgraph
            qgraph.install(model, verbose=False, mode=graph_mode)
            graph_on = graph_mode
        except Exception as e:                                   # noqa: BLE001
            # 소리가 먼저다 — 못 꽂으면 그냥 옛 길로 간다(느릴 뿐, 굽기는 된다).
            print("[qgraph] 못 꽂았다 — 옛 길로 간다: %s: %s"
                  % (type(e).__name__, e), file=sys.stderr, flush=True)

    def bake_one(text):
        wavs, sr = model.generate_voice_clone(text=text, language="Korean",
                                              ref_audio=REF_WAV, ref_text=ref_text)
        w = wavs[0]
        if hasattr(w, "detach"):
            w = w.detach().float().cpu().numpy()
        return w, sr

    @torch.no_grad()
    def bake_batch(texts):
        """여러 조각을 **한 번에** 굽는다. [왜] 자기회귀라 걸리는 시간은 묶음 안에서 가장
        긴 조각이 정한다 — 넷을 묶어도 하나 굽는 시간에서 크게 안 는다(실측 조각당
        22.1초 → 2.3초, RTF 6.14 → 0.75).
        [🔴 소리는 하나씩 만든다] 묶은 채로 디코드하면 conv1d 가 봉우리를 만들어 배치 4에서
          VRAM 이 터졌다(ac_batch_bench 실측). 굽기만 묶고 디코드는 하나씩 돈다.
        [🔴 라이브러리 속을 쓴다] qwen_tts 판이 바뀌면 여기가 깨진다. 깨지면 부모가
          한 조각씩 굽는 길로 돌아가게 되어 있다(ag_bake_now 의 fallback)."""
        items = [prompt[0]] * len(texts)
        vcp = model._prompt_items_to_voice_clone_prompt(items)                       # noqa: SLF001
        ids = model._tokenize_texts([model._build_assistant_text(t) for t in texts])  # noqa: SLF001
        rids = [model._tokenize_texts([model._build_ref_text(it.ref_text)])[0]        # noqa: SLF001
                for it in items]
        codes, _ = model.model.generate(input_ids=ids, ref_ids=rids, voice_clone_prompt=vcp,
                                        languages=["Korean"] * len(texts),
                                        non_streaming_mode=False,
                                        **model._merge_generate_kwargs())            # noqa: SLF001
        outs, sr = [], None
        for i, c in enumerate(codes):
            rc = vcp["ref_code"][i]
            full = torch.cat([rc.to(c.device), c], dim=0)
            wavs, sr = model.model.speech_tokenizer.decode([{"audio_codes": full}])
            w = wavs[0]
            w = w[int(int(rc.shape[0]) / max(int(full.shape[0]), 1) * w.shape[0]):]
            if hasattr(w, "detach"):
                w = w.detach().float().cpu().numpy()
            outs.append(w)
            del wavs, full
        return outs, sr

    out({"ok": True, "ready": True, "load_s": round(time.time() - t0, 1),
         "free_mb": gpu_free_mb(), "graph": graph_on})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            out({"ok": False, "error": "bad json"})
            continue
        cmd = req.get("cmd", "say")
        if cmd == "quit":
            break
        if cmd == "ping":
            out({"ok": True, "ready": True, "free_mb": gpu_free_mb()})
            continue

        if cmd == "say_parts":
            # [🔴 첫 조각을 홀로 먼저, 나머지는 묶어서] 첫 소리는 첫 조각의 길이가 정한다
            #   (RTF 8 은 모델 구조라 못 내린다 — 우리가 정할 수 있는 것은 조각 크기뿐이다).
            #   그래서 첫 조각만 짧게 혼자 굽고 **그 자리에서 답을 한 번 보낸다**(부모가
            #   기다리지 않고 바로 올린다). 나머지는 한 번에 묶어 굽는다.
            parts = req.get("parts") or []
            first_out, dst = req.get("first_out", ""), req.get("out", "")
            # 조각마다 파일을 따로 남긴다 — 부모가 **하나씩 올리기** 위해서다.
            # 묶어 굽는 것과 하나씩 올리는 것은 서로 다른 문제다: 굽기는 묶어야 빠르고,
            # 올리기는 나눠야 보드가 이어 붙일 수 있다.
            prefix = req.get("prefix", "")
            if not parts or not dst:
                out({"ok": False, "error": "no parts/out"})
                continue
            try:
                t = time.time()
                # [🔴 첫 조각은 참조를 다시 만지지 않는다] generate_voice_clone() 은 부를
                #   때마다 ref_audio 를 다시 거친다(실측 첫 1.71초, 그 뒤 0.31초). 첫 조각이
                #   10초짜리인데 그 0.3초가 매번 앞에 붙는다. 뜰 때 한 번 만들어 둔
                #   prompt 를 그대로 쓰는 길(bake_batch)로 첫 조각도 굽는다.
                w0s, sr = bake_batch([parts[0]])
                w0 = w0s[0]
                if first_out:
                    tmp = first_out + ".part"
                    sf.write(tmp, w0, sr, subtype="PCM_16", format="WAV")
                    os.replace(tmp, first_out)
                out({"ok": True, "stage": "first", "sec": round(time.time() - t, 2),
                     "dur": round(len(w0) / sr, 2), "chars": len(parts[0])})
            except Exception as e:                               # noqa: BLE001
                out({"ok": False, "stage": "first", "error": f"{type(e).__name__}: {e}"})
                continue
            try:
                t = time.time()
                rest = []
                if len(parts) > 1:
                    # [🔴 나머지는 한 번에 묶어 굽는다] 커널을 하나씩 띄우는 값이 시간을
                    #   다 먹는다(실측: 배치1 22.1초 vs 배치16 36.9초 — 일 16배에 시간 1.7배).
                    #   묶으면 그 값이 나뉘어 조각당 시간이 뚝 떨어진다.
                    rest, sr2 = bake_batch(parts[1:])
                    sr = sr2 or sr
                # 조각마다 파일로 남긴다 — 부모가 순서대로 하나씩 올린다(보드가 이어 붙인다).
                durs = [round(len(w0) / sr, 2)]
                if prefix:
                    sf.write(prefix + ".p00.wav", w0, sr, subtype="PCM_16", format="WAV")
                for i, w in enumerate(rest, start=1):
                    if prefix:
                        sf.write(prefix + (".p%02d.wav" % i), w, sr,
                                 subtype="PCM_16", format="WAV")
                    durs.append(round(len(w) / sr, 2))
                # 조각 사이에 짧은 숨을 넣는다 — 붙이는 자리가 딱 붙으면 말이 뭉친다.
                gap = np.zeros(int(sr * 0.10), dtype=np.float32)
                full = w0
                for w in rest:
                    full = np.concatenate([full, gap, w.astype(np.float32)])
                tmp = dst + ".part"
                sf.write(tmp, full, sr, subtype="PCM_16", format="WAV")
                os.replace(tmp, dst)
                out({"ok": True, "stage": "full", "sec": round(time.time() - t, 2),
                     "dur": round(len(full) / sr, 2), "n": len(parts), "durs": durs,
                     "free_mb": gpu_free_mb()})
            except Exception as e:                               # noqa: BLE001
                out({"ok": False, "stage": "full", "error": f"{type(e).__name__}: {e}"})
            continue

        text, dst = req.get("text", ""), req.get("out", "")
        if not text or not dst:
            out({"ok": False, "error": "no text/out"})
            continue
        # [🔴 여기서 아무것도 재지 않는다 — 그냥 굽는다] 전에는 굽기 전마다 여유를 보고
        #   모자라면 물러났다. 그 판단이 사장을 11분 기다리게 했다. 자리가 모자라면
        #   아래 generate 가 OutOfMemoryError 로 터지고, 부모가 나를 내려 GPU 를 학습에
        #   돌려준 뒤 다음 쪽지에 다시 띄운다. **구울 수 있는지는 구워 봐야 안다.**
        try:
            t = time.time()
            wavs, sr = model.generate_voice_clone(text=text, language="Korean",
                                                  ref_audio=REF_WAV, ref_text=ref_text)
            w = wavs[0]
            if hasattr(w, "detach"):
                w = w.detach().float().cpu().numpy()
            tmp = dst + ".part"
            sf.write(tmp, w, sr, subtype="PCM_16", format="WAV")
            os.replace(tmp, dst)
            out({"ok": True, "sec": round(time.time() - t, 2),
                 "dur": round(len(w) / sr, 2), "free_mb": gpu_free_mb()})
        except Exception as e:                                   # noqa: BLE001
            out({"ok": False, "error": f"{type(e).__name__}: {e}"})

    try:
        # [🔴 원본과 갈라진 자리 ⑤ — `del model` 이 아니라 None 을 넣는다]
        #   `del` 은 이름을 **없앤다**. 위 bake_one/bake_batch 가 이 이름을 닫아 쥐고
        #   있어서, 정적 분석기(ruff)가 그 둘 안의 model 을 '없는 이름'(F821)으로 읽는다.
        #   이 파일은 이제 .ai_monitor 아래에 있고 CI 가 그 폴더를 린트하므로,
        #   그대로 두면 **빌드가 통째로 떨어진다**(보드 원본도 같은 9건이 뜬다).
        #   None 을 넣어도 참조가 끊겨 메모리는 똑같이 풀린다.
        model = None                                             # noqa: F841
        torch.cuda.empty_cache()
    except Exception:                                            # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
