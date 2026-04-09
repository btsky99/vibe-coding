/**
 * ------------------------------------------------------------------------
 * FILE: useCliModels.ts
 * DESCRIPTION: CLI별 사용 가능한 모델 목록 조회 훅.
 *              PTY 서버의 /api/pty/models에서 동적으로 가져오며,
 *              실패 시 하드코딩 폴백 목록을 반환한다.
 * REVISION HISTORY:
 * - 2026-04-09 Claude: Gemini/Codex 폴백 모델을 2026-04 기준 최신으로 교체.
 *                     Gemini: 2.5 계열 → 3.1 계열 (3.1 Pro / Flash / Flash-Lite).
 *                     Codex: o3/o4-mini/gpt-4.1 → gpt-5.3-codex / gpt-5.4-mini.
 * - 2026-04-08 Claude: 초기 생성 — 오피스 워크스페이스 프로필 모델 선택용
 * ------------------------------------------------------------------------
 */

import { useEffect, useState } from 'react';

export interface ModelOption {
  id: string;
  label: string;
}

export type CliModelMap = Record<string, ModelOption[]>;

// ── 폴백 (서버 미응답 시) ─────────────────────────────────────────────────

const FALLBACK_MODELS: CliModelMap = {
  claude: [
    { id: 'claude-opus-4-6', label: 'Opus 4.6 (최강)' },
    { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6 (균형)' },
    { id: 'claude-haiku-4-5', label: 'Haiku 4.5 (경량)' },
  ],
  gemini: [
    { id: 'gemini-3.1-pro', label: '3.1 Pro (최강)' },
    { id: 'gemini-3.1-flash', label: '3.1 Flash (빠름)' },
    { id: 'gemini-3.1-flash-lite', label: '3.1 Flash-Lite (저지연)' },
    { id: 'gemini-2.5-pro', label: '2.5 Pro (레거시)' },
  ],
  codex: [
    { id: 'gpt-5.3-codex', label: 'GPT-5.3-Codex (최강)' },
    { id: 'gpt-5.3-codex-spark', label: 'GPT-5.3-Codex Spark (실시간)' },
    { id: 'gpt-5.4', label: 'GPT-5.4 (범용)' },
    { id: 'gpt-5.4-mini', label: 'GPT-5.4 Mini (빠름)' },
    { id: 'gpt-5.2-codex', label: 'GPT-5.2-Codex (이전 세대)' },
  ],
};

const CACHE_DURATION_MS = 5 * 60 * 1000;

let cachedModels: CliModelMap | null = null;
let cacheTimestamp = 0;

export function useCliModels(): CliModelMap {
  const [models, setModels] = useState<CliModelMap>(cachedModels || FALLBACK_MODELS);

  useEffect(() => {
    if (cachedModels && Date.now() - cacheTimestamp < CACHE_DURATION_MS) {
      setModels(cachedModels);
      return;
    }

    fetch('/api/pty/models')
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: CliModelMap) => {
        cachedModels = data;
        cacheTimestamp = Date.now();
        setModels(data);
      })
      .catch(() => {
        setModels(FALLBACK_MODELS);
      });
  }, []);

  return models;
}

export function getDefaultModel(cli: string): string {
  const list = FALLBACK_MODELS[cli];
  return list ? list[0].id : '';
}
