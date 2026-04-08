/**
 * ------------------------------------------------------------------------
 * FILE: useCliModels.ts
 * DESCRIPTION: CLI별 사용 가능한 모델 목록 조회 훅.
 *              PTY 서버의 /api/pty/models에서 동적으로 가져오며,
 *              실패 시 하드코딩 폴백 목록을 반환한다.
 * REVISION HISTORY:
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
    { id: 'gemini-2.5-pro', label: '2.5 Pro (최강)' },
    { id: 'gemini-2.5-flash', label: '2.5 Flash (빠름)' },
    { id: 'gemini-2.0-flash', label: '2.0 Flash (저지연)' },
  ],
  codex: [
    { id: 'o4-mini', label: 'o4-mini (기본)' },
    { id: 'o3', label: 'o3 (고급 추론)' },
    { id: 'gpt-4.1', label: 'GPT-4.1 (플래그십)' },
    { id: 'gpt-4.1-mini', label: 'GPT-4.1 Mini (빠름)' },
    { id: 'gpt-4.1-nano', label: 'GPT-4.1 Nano (최경량)' },
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
