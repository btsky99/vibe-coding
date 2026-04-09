/**
 * ------------------------------------------------------------------------
 * FILE: OfficeCanvas.tsx
 * DESCRIPTION: 메타버스 오피스 Phase 3 — Phaser.js 기반 실제 게임 월드.
 *              DOM 동그라미(OfficeWorld) 완전 대체. 타일 바닥 + 방 구획 +
 *              움직이는 에이전트 스프라이트 + idle bob + walk 애니메이션.
 * REVISION HISTORY:
 * - 2026-04-09 Claude: Step 1.2 — 책상/의자/모니터 가구 추가 + 미니 휴머노이드 캐릭터.
 *                      (1) createMiniCharacter: Phaser Graphics 프리미티브로 머리/몸통/다리 조합
 *                      (2) 책상 + 모니터 + 의자 가구 렌더 (코딩 부서 9개, 대표실 1개, 회의실 테이블)
 *                      (3) 에이전트가 자기 책상에 고정 — 랜덤 산책 AI 제거 (어지러움)
 *                      (4) idle bob만 유지 (숨쉬는 효과)
 *                      (5) fingerprint 기반 rebuild — ghost 스프라이트 누적 버그 수정
 * - 2026-04-09 Claude: Step 1.0 — 움직임/애니메이션 초안 (공 굴러다님 단계. 캐릭터·책상 없음)
 * - 2026-04-09 Claude: Step 0 — 최초 생성. Phaser Game + 방 레이아웃 + 정적 배치
 * ------------------------------------------------------------------------
 */

import { useEffect, useRef } from 'react';
import Phaser from 'phaser';
import type {
  OfficeAgentPresence,
  OfficeEventCard,
  OfficeZoneState,
  OfficeZone,
} from '../../hooks/useOfficeState';

interface SpeechBubble {
  deskId: number;
  text: string;
  createdAt: number;
  duration: number;
}

interface OfficeCanvasProps {
  presences: OfficeAgentPresence[];
  zones: OfficeZoneState[];
  events: OfficeEventCard[];
  selectedDesk: number;
  onDeskClick: (slotId: number) => void;
  onZoneClick?: (zone: OfficeZone) => void;
  speechBubbles?: SpeechBubble[];
  slotNames?: string[];
  slotRoles?: string[];
}

// CLI별 컬러 팔레트
const CLI_COLORS: Record<string, number> = {
  claude: 0xa78bfa,
  gemini: 0x34d399,
  codex: 0x22d3ee,
  user: 0xfbbf24,
  unknown: 0x94a3b8,
};

const WORLD_WIDTH = 1280;
const WORLD_HEIGHT = 720;
const WALK_SPEED = 90; // px/sec

// 방 경계 — 회의실이 가장 크고 탕비실은 작은 휴게 공간
type RoomRect = { x: number; y: number; w: number; h: number };
const ROOMS: Record<string, RoomRect> = {
  user:    { x: 20,  y: 20,  w: 300, h: 240 },  // 대표실
  pantry:  { x: 340, y: 20,  w: 240, h: 240 },  // 탕비실 (작게)
  meeting: { x: 600, y: 20,  w: 660, h: 240 },  // 회의실 (크게 — 주 회의 공간)
  desk:    { x: 340, y: 280, w: 600, h: 500 },  // 코딩 부서 (LimeZu 3×3 간격 위해 h 420→500)
};

// 캐릭터 전체 스케일 — 얼굴 디테일이 보이도록 크게
const CHARACTER_SCALE = 1.6;

// LimeZu 캐릭터 스프라이트 — Modern Interiors Free 라이선스 (비상업용)
// 각 idle_anim은 24 frames of 16x32
const LIMEZU_CHAR_KEYS = ['adam', 'alex', 'amelia', 'bob'] as const;
const LIMEZU_SPRITE_SCALE = 4;  // 16x32 * 4 = 64x128 — 얼굴 디테일이 잘 보임

/**
 * 에이전트 하나의 상태 — 컨테이너 + 이동 목표 + 애니메이션 페이즈.
 * Phaser GameObject와 별도로 관리해서 루프에서 쉽게 제어한다.
 */
interface AgentState {
  container: Phaser.GameObjects.Container;
  sprite?: Phaser.GameObjects.Sprite;  // LimeZu 스프라이트 모드일 때 사용
  // ── 아래는 프리미티브 모드 전용 (점진적 마이그레이션 중) ──
  body?: Phaser.GameObjects.Container;
  leftLeg?: Phaser.GameObjects.Rectangle;
  rightLeg?: Phaser.GameObjects.Rectangle;
  leftArm?: Phaser.GameObjects.Rectangle;
  rightArm?: Phaser.GameObjects.Rectangle;
  leftHand?: Phaser.GameObjects.Arc;
  rightHand?: Phaser.GameObjects.Arc;
  leftEye?: Phaser.GameObjects.Arc;
  rightEye?: Phaser.GameObjects.Arc;
  head?: Phaser.GameObjects.Arc;
  // ── 공통 상태 ──
  homeX: number;
  homeY: number;
  targetX: number;
  targetY: number;
  bobPhase: number;
  typingPhase: number;
  blinkAt: number;
  roomId: string;
  isWalking: boolean;
  isAtDesk: boolean;
  lastDecisionAt: number;
  nextDecisionAt: number;
}

/**
 * 역할(role)별 특수 표현 — 악세사리, 머리색 등.
 * pg_store.py의 에이전트 role 값과 매칭된다 (ceo/planner/architect/frontend/...).
 */
interface RoleStyle {
  hairColor: number;   // 머리카락 색
  accessory?: 'crown' | 'notebook' | 'glasses' | 'magnifier' | 'wrench' | 'shield' | 'pen';
  skinTone: number;
}

const ROLE_STYLES: Record<string, RoleStyle> = {
  ceo:       { hairColor: 0x1f2937, skinTone: 0xfde68a, accessory: 'crown' },
  planner:   { hairColor: 0x422006, skinTone: 0xfde68a, accessory: 'notebook' },
  architect: { hairColor: 0x78350f, skinTone: 0xfcd34d, accessory: 'pen' },
  frontend:  { hairColor: 0x7c2d12, skinTone: 0xfde68a, accessory: 'glasses' },
  backend:   { hairColor: 0x1e293b, skinTone: 0xfcd34d, accessory: 'glasses' },
  fullstack: { hairColor: 0xdc2626, skinTone: 0xfde68a, accessory: 'pen' },
  reviewer:  { hairColor: 0x374151, skinTone: 0xfcd34d, accessory: 'magnifier' },
  qa:        { hairColor: 0x6b21a8, skinTone: 0xfde68a, accessory: 'magnifier' },
  security:  { hairColor: 0x0f172a, skinTone: 0xfcd34d, accessory: 'shield' },
  devops:    { hairColor: 0x92400e, skinTone: 0xfde68a, accessory: 'wrench' },
  unknown:   { hairColor: 0x78350f, skinTone: 0xfcd34d },
};

/**
 * Phaser Graphics로 미니 휴머노이드 캐릭터 생성 (Step 1.3 버전).
 *
 * 구성: 그림자 + 다리 2 + 신발 2 + 몸통 + 팔 2 + 목 + 머리(얼굴+머리카락+눈+입) + 악세사리
 * 크기: 약 40x60 (이전 20x30에서 2배). 멀리서도 사람 실루엣이 보임.
 */
function createMiniCharacter(
  scene: Phaser.Scene,
  shirtColor: number,
  role: string,
  _letter: string,
): {
  body: Phaser.GameObjects.Container;
  head: Phaser.GameObjects.Arc;
  leftLeg: Phaser.GameObjects.Rectangle;
  rightLeg: Phaser.GameObjects.Rectangle;
  leftArm: Phaser.GameObjects.Rectangle;
  rightArm: Phaser.GameObjects.Rectangle;
  leftHand: Phaser.GameObjects.Arc;
  rightHand: Phaser.GameObjects.Arc;
  leftEye: Phaser.GameObjects.Arc;
  rightEye: Phaser.GameObjects.Arc;
} {
  const style = ROLE_STYLES[role.toLowerCase()] || ROLE_STYLES.unknown;
  const body = scene.add.container(0, 0);

  // ── 그림자 (발밑) — 공중에 떠있는 느낌 제거 ──
  const shadow = scene.add.ellipse(0, 26, 22, 5, 0x000000, 0.4);

  // ── 다리 (바지) ──
  const leftLeg = scene.add.rectangle(-5, 16, 5, 10, 0x1e3a8a).setOrigin(0.5, 0);
  leftLeg.setStrokeStyle(1, 0x0f172a, 0.6);
  const rightLeg = scene.add.rectangle(5, 16, 5, 10, 0x1e3a8a).setOrigin(0.5, 0);
  rightLeg.setStrokeStyle(1, 0x0f172a, 0.6);

  // ── 신발 ──
  const leftShoe = scene.add.rectangle(-5, 26, 7, 3, 0x0f172a).setOrigin(0.5, 0);
  const rightShoe = scene.add.rectangle(5, 26, 7, 3, 0x0f172a).setOrigin(0.5, 0);

  // ── 몸통 (셔츠) ──
  const torso = scene.add.rectangle(0, 8, 22, 16, shirtColor).setOrigin(0.5, 0.5);
  torso.setStrokeStyle(1, 0x000000, 0.4);
  // 셔츠 하이라이트 (왼쪽)
  const torsoHL = scene.add.rectangle(-8, 4, 2, 12, 0xffffff, 0.2).setOrigin(0.5, 0.5);
  // 셔츠 V넥 (어두운 선)
  const vneck = scene.add.triangle(0, 2, -3, 0, 3, 0, 0, 4, 0x000000, 0.3);

  // ── 팔 2개 ──
  const leftArm = scene.add.rectangle(-13, 8, 4, 14, shirtColor).setOrigin(0.5, 0.5);
  leftArm.setStrokeStyle(1, 0x000000, 0.4);
  const rightArm = scene.add.rectangle(13, 8, 4, 14, shirtColor).setOrigin(0.5, 0.5);
  rightArm.setStrokeStyle(1, 0x000000, 0.4);
  // 손 (살색 원)
  const leftHand = scene.add.circle(-13, 15, 2.2, style.skinTone);
  const rightHand = scene.add.circle(13, 15, 2.2, style.skinTone);

  // ── 목 ──
  const neck = scene.add.rectangle(0, -2, 5, 4, style.skinTone).setOrigin(0.5, 0.5);

  // ── 머리 (얼굴) ──
  const head = scene.add.circle(0, -12, 9, style.skinTone);
  head.setStrokeStyle(1, 0x000000, 0.4);

  // ── 머리카락 (앞머리) ──
  const hairTop = scene.add.ellipse(0, -18, 17, 9, style.hairColor);
  const hairSide1 = scene.add.circle(-7, -14, 3, style.hairColor);
  const hairSide2 = scene.add.circle(7, -14, 3, style.hairColor);

  // ── 눈 2개 ──
  const leftEye = scene.add.circle(-3, -12, 1.2, 0x000000);
  const rightEye = scene.add.circle(3, -12, 1.2, 0x000000);
  // 눈 하이라이트 (생기)
  const leftEyeHL = scene.add.circle(-2.6, -12.4, 0.4, 0xffffff);
  const rightEyeHL = scene.add.circle(3.4, -12.4, 0.4, 0xffffff);

  // ── 입 (미소) ──
  const mouth = scene.add.rectangle(0, -8, 3, 0.8, 0x7c2d12).setOrigin(0.5, 0.5);

  // ── 볼 홍조 ──
  const blushL = scene.add.circle(-5, -10, 1.2, 0xf87171, 0.5);
  const blushR = scene.add.circle(5, -10, 1.2, 0xf87171, 0.5);

  // ── 기본 요소 컨테이너에 등록 (뒤쪽부터) ──
  body.add([
    shadow,
    leftLeg, rightLeg, leftShoe, rightShoe,
    leftArm, rightArm,
    torso, torsoHL, vneck,
    leftHand, rightHand,
    neck,
    head,
    hairTop, hairSide1, hairSide2,
    leftEye, rightEye, leftEyeHL, rightEyeHL,
    mouth,
    blushL, blushR,
  ]);

  // ── 역할별 악세사리 ──
  addAccessory(scene, body, style.accessory);

  // ── 전체 캐릭터 스케일 ──
  body.setScale(CHARACTER_SCALE);

  return { body, head, leftLeg, rightLeg, leftArm, rightArm, leftHand, rightHand, leftEye, rightEye };
}

/**
 * 역할별 악세사리를 캐릭터 컨테이너에 추가.
 */
function addAccessory(
  scene: Phaser.Scene,
  body: Phaser.GameObjects.Container,
  accessory?: string,
) {
  if (!accessory) return;

  switch (accessory) {
    case 'crown': {
      // 황금 왕관 (머리 위)
      const base = scene.add.rectangle(0, -22, 16, 2, 0xfbbf24).setOrigin(0.5, 0.5);
      base.setStrokeStyle(1, 0x92400e);
      const spike1 = scene.add.triangle(-5, -26, -2, 0, 2, 0, 0, -4, 0xfbbf24);
      const spike2 = scene.add.triangle(0, -26, -2, 0, 2, 0, 0, -4, 0xfbbf24);
      const spike3 = scene.add.triangle(5, -26, -2, 0, 2, 0, 0, -4, 0xfbbf24);
      const gem = scene.add.circle(0, -25, 1, 0xef4444);
      body.add([base, spike1, spike2, spike3, gem]);
      break;
    }
    case 'notebook': {
      // 노트 (팔 옆)
      const pad = scene.add.rectangle(-16, 10, 6, 8, 0xf1f5f9).setOrigin(0.5, 0.5);
      pad.setStrokeStyle(1, 0x475569);
      const line1 = scene.add.rectangle(-16, 9, 4, 0.5, 0x64748b).setOrigin(0.5, 0.5);
      const line2 = scene.add.rectangle(-16, 11, 4, 0.5, 0x64748b).setOrigin(0.5, 0.5);
      body.add([pad, line1, line2]);
      break;
    }
    case 'glasses': {
      // 안경 (얼굴 위 덮기)
      const leftLens = scene.add.circle(-3, -12, 2.5);
      leftLens.setStrokeStyle(1, 0x0f172a);
      const rightLens = scene.add.circle(3, -12, 2.5);
      rightLens.setStrokeStyle(1, 0x0f172a);
      const bridge = scene.add.rectangle(0, -12, 1.5, 0.5, 0x0f172a).setOrigin(0.5, 0.5);
      body.add([leftLens, rightLens, bridge]);
      break;
    }
    case 'magnifier': {
      // 돋보기 (오른손)
      const ring = scene.add.circle(17, 12, 3);
      ring.setStrokeStyle(1.5, 0xfcd34d);
      const handle = scene.add.rectangle(20, 15, 1, 4, 0x78350f).setOrigin(0.5, 0);
      body.add([ring, handle]);
      break;
    }
    case 'wrench': {
      // 렌치 (오른손)
      const body1 = scene.add.rectangle(17, 12, 1.5, 8, 0x94a3b8).setOrigin(0.5, 0.5);
      const head1 = scene.add.rectangle(17, 8, 4, 2, 0x94a3b8).setOrigin(0.5, 0.5);
      body.add([body1, head1]);
      break;
    }
    case 'shield': {
      // 방패 (왼손)
      const shieldBase = scene.add.triangle(-17, 10, -4, -5, 4, -5, 0, 6, 0x1e40af);
      shieldBase.setStrokeStyle(1, 0xfbbf24);
      const cross1 = scene.add.rectangle(-17, 9, 0.8, 5, 0xfbbf24).setOrigin(0.5, 0.5);
      const cross2 = scene.add.rectangle(-17, 9, 3, 0.8, 0xfbbf24).setOrigin(0.5, 0.5);
      body.add([shieldBase, cross1, cross2]);
      break;
    }
    case 'pen': {
      // 펜 (오른손)
      const shaft = scene.add.rectangle(15, 13, 1, 6, 0x0f172a).setOrigin(0.5, 0.5);
      const tip = scene.add.triangle(15, 16, -0.5, 0, 0.5, 0, 0, 1.5, 0xfbbf24);
      body.add([shaft, tip]);
      break;
    }
  }
}

class OfficeScene extends Phaser.Scene {
  private agents: Map<number, AgentState> = new Map();
  private selectedRing: Phaser.GameObjects.Graphics | null = null;
  public isReady = false;

  public presences: OfficeAgentPresence[] = [];
  public selectedDesk: number = 0;
  public slotNames: string[] = [];
  public slotRoles: string[] = [];
  public onDeskClick: (slotId: number) => void = () => {};

  /**
   * 마지막으로 처리한 presences의 "신원 지문" — slotId + agent + name 조합.
   * 동일하면 rebuild 스킵해서 ghost 누적 방지.
   */
  private lastPresenceFingerprint: string = '';

  constructor() {
    super({ key: 'OfficeScene' });
  }

  preload() {
    // LimeZu 캐릭터 스프라이트시트 로드 (16x32 frames, 24 frames idle anim)
    LIMEZU_CHAR_KEYS.forEach((key) => {
      const name = key.charAt(0).toUpperCase() + key.slice(1);
      this.load.spritesheet(
        `char_${key}_idle`,
        `/assets/limezu/characters/${name}_idle_anim_16x16.png`,
        { frameWidth: 16, frameHeight: 32 },
      );
    });

    // LimeZu 바닥 타일 — 16x16 단일 패턴, TileSprite로 반복
    const floorTiles = [
      'floor_herringbone', 'floor_concrete', 'floor_teal',
      'floor_yellow', 'floor_brick',
    ];
    floorTiles.forEach((t) => {
      this.load.image(`tile_${t}`, `/assets/limezu/tiles/${t}.png`);
    });

    // LimeZu 가구 스프라이트
    const furniture = ['desk_plain', 'chair_side', 'plant_large'];
    furniture.forEach((f) => {
      this.load.image(`furn_${f}`, `/assets/limezu/tiles/${f}.png`);
    });
  }

  create() {
    // ── LimeZu 캐릭터 idle 애니메이션 등록 ──
    LIMEZU_CHAR_KEYS.forEach((key) => {
      const animKey = `anim_${key}_idle`;
      if (!this.anims.exists(animKey)) {
        this.anims.create({
          key: animKey,
          frames: this.anims.generateFrameNumbers(`char_${key}_idle`, { start: 0, end: 23 }),
          frameRate: 8,
          repeat: -1,
        });
      }
    });

    this.cameras.main.setBackgroundColor('#0a0a0f');

    // ── 전체 바닥 (한 덩어리 오피스) ──
    this.drawOfficeFloor();

    // ── 외곽 벽 (회사 경계) ──
    this.drawOuterWalls();

    // ── 복도/구역 표시 (벽 없이 카펫·러그로 구역 구분) ──
    this.drawZoneFloors();

    // ── 구역 라벨 (방 이름) ──
    this.drawZoneLabel(ROOMS.user, '대표실', 0xfbbf24);
    this.drawZoneLabel(ROOMS.pantry, '탕비실', 0xf97316);
    this.drawZoneLabel(ROOMS.meeting, '회의실', 0x22d3ee);
    this.drawZoneLabel(ROOMS.desk, '코딩 부서', 0xa78bfa);

    // ── 가구 배치 ──
    this.drawFurniture();
    this.drawPantry();
    this.drawPlantsAndLamps();

    // 선택 링
    this.selectedRing = this.add.graphics();

    this.rebuildAgents();
    this.isReady = true;

    // ── 카메라 줌 (마우스 휠) + 드래그 팬 ──
    this.setupCameraControls();
  }

  /**
   * 마우스 휠로 줌, 우클릭 드래그로 팬.
   * 얼굴 디테일 확인 및 디버깅용.
   */
  private setupCameraControls() {
    const cam = this.cameras.main;
    cam.setZoom(1);

    // 휠 줌
    this.input.on('wheel', (_ptr: Phaser.Input.Pointer, _go: unknown, _dx: number, dy: number) => {
      const current = cam.zoom;
      const next = Phaser.Math.Clamp(current - dy * 0.001, 0.5, 3.5);
      cam.setZoom(next);
    });

    // 드래그 팬 (가운데 버튼 또는 우클릭)
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let camStartX = 0;
    let camStartY = 0;

    this.input.on('pointerdown', (ptr: Phaser.Input.Pointer) => {
      if (ptr.rightButtonDown() || ptr.middleButtonDown()) {
        isDragging = true;
        dragStartX = ptr.x;
        dragStartY = ptr.y;
        camStartX = cam.scrollX;
        camStartY = cam.scrollY;
      }
    });
    this.input.on('pointermove', (ptr: Phaser.Input.Pointer) => {
      if (!isDragging) return;
      const dx = (ptr.x - dragStartX) / cam.zoom;
      const dy = (ptr.y - dragStartY) / cam.zoom;
      cam.setScroll(camStartX - dx, camStartY - dy);
    });
    this.input.on('pointerup', () => { isDragging = false; });
    this.input.on('pointerupoutside', () => { isDragging = false; });

    // 우클릭 컨텍스트 메뉴 차단 (캔버스 위에서만)
    const gameCanvas = this.game.canvas;
    if (gameCanvas) {
      gameCanvas.addEventListener('contextmenu', (e) => e.preventDefault());
    }
  }

  /**
   * 전체 바닥 — LimeZu 헤링본 원목 타일로 반복.
   * 한 덩어리 오피스 느낌. TileSprite는 텍스처를 자동으로 repeat한다.
   */
  private drawOfficeFloor() {
    // 기본 바닥색 (타일 로드 전 폴백)
    const base = this.add.rectangle(
      WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
      WORLD_WIDTH, WORLD_HEIGHT, 0x1c1917,
    );
    base.setDepth(-10);

    // 실제 타일 바닥 — 16x16을 화면에 맞게 반복
    // scale 2 → 32x32 실제 타일 크기 (캐릭터와 비율 맞춤)
    const tileSprite = this.add.tileSprite(
      WORLD_WIDTH / 2, WORLD_HEIGHT / 2,
      WORLD_WIDTH, WORLD_HEIGHT,
      'tile_floor_herringbone',
    );
    tileSprite.setTileScale(2, 2);
    tileSprite.setDepth(-9);
  }

  /**
   * 외곽 벽 — 회사 전체 경계. 부드러운 라운드 + 두꺼운 선.
   */
  private drawOuterWalls() {
    const walls = this.add.graphics();
    walls.lineStyle(4, 0x475569, 0.8);
    walls.strokeRoundedRect(10, 10, WORLD_WIDTH - 20, WORLD_HEIGHT - 20, 16);
    walls.setDepth(-5);
  }

  /**
   * 각 구역에 은은한 카펫 색 깔기 (벽 없이 구역만 구분).
   * 서로 overlap해도 자연스럽게 이어지도록 매우 옅은 채도로.
   */
  private drawZoneFloors() {
    const zones: Array<[RoomRect, number]> = [
      [ROOMS.user, 0xfbbf24],
      [ROOMS.pantry, 0xf97316],
      [ROOMS.meeting, 0x22d3ee],
      [ROOMS.desk, 0xa78bfa],
    ];
    zones.forEach(([r, color]) => {
      const carpet = this.add.rectangle(
        r.x + r.w / 2,
        r.y + r.h / 2,
        r.w - 10,
        r.h - 10,
        color,
        0.06,
      );
      carpet.setDepth(-4);
      // 구역 테두리 (매우 얇게, 점선 느낌)
      const border = this.add.graphics();
      border.lineStyle(1, color, 0.2);
      border.strokeRoundedRect(r.x, r.y, r.w, r.h, 10);
      border.setDepth(-3);
    });

    // ── 중앙 복도 (대표실 아래 ~ 코딩부서 위 연결) ──
    // 탕비실/회의실도 이 복도로 간다는 표식 역할.
    const hallway = this.add.rectangle(
      WORLD_WIDTH / 2,
      270,
      WORLD_WIDTH - 60,
      14,
      0x44403c,
      0.3,
    );
    hallway.setStrokeStyle(1, 0x78716c, 0.3);
    hallway.setDepth(-3);
  }

  /**
   * 구역 라벨만 — 벽 없이 텍스트만 띄움.
   */
  private drawZoneLabel(r: RoomRect, label: string, color: number) {
    const text = this.add.text(r.x + 16, r.y + 10, label, {
      fontFamily: 'system-ui, -apple-system, sans-serif',
      fontSize: '13px',
      fontStyle: 'bold',
      color: `#${color.toString(16).padStart(6, '0')}`,
    });
    text.setDepth(-2);
  }

  /**
   * 오피스 가구 렌더 — 책상, 모니터, 의자.
   * 에이전트 위치와 동기화: computePosition에서 계산한 것과 같은 좌표를 공유한다.
   */
  private drawFurniture() {
    // ── 대표실 (x=170, y=150) — 새 레이아웃 중심 ──
    this.drawExecutiveDesk(170, 150);

    // ── 회의실 (x=930, y=150) — 넓어진 방 중앙 ──
    this.drawMeetingTable(930, 150);

    // ── 코딩 부서: 9개 책상 (3x3, 간격 150으로 넓힘) ──
    for (let i = 0; i < 9; i++) {
      const col = i % 3;
      const row = Math.floor(i / 3);
      const x = 440 + col * 200;
      const y = 410 + row * 150;
      this.drawCodingDesk(x, y);
    }
  }

  /**
   * 코딩 부서 책상 1개 — LimeZu 스프라이트 (desk + chair).
   * 탑다운 뷰에서 "책상에 앉은" 느낌을 내기 위해 아래 레이어 순서:
   *  의자(뒤, depth 2) → 책상(아래쪽, depth 8) → 캐릭터(상체만 책상 위로 나옴, depth 10)
   * (x, y)는 에이전트 자리의 "발" 위치.
   */
  private drawCodingDesk(x: number, y: number) {
    const FURN_SCALE = 4;  // 캐릭터와 같은 4x

    // 책상 — 캐릭터 바로 아래쪽에 배치 (탑다운 뷰에서 책상이 앞에 옴)
    const desk = this.add.image(x, y + 40, 'furn_desk_plain');
    desk.setScale(FURN_SCALE);
    desk.setDepth(8);  // 캐릭터(10) 뒤지만 바닥(-9)보다 앞

    // 의자 — 캐릭터 뒤쪽 (위)
    const chair = this.add.image(x, y - 70, 'furn_chair_side');
    chair.setScale(FURN_SCALE);
    chair.setFlipX(true);  // 정면 향하게
    chair.setDepth(2);
  }

  /**
   * 대표실 큰 책상 — 코딩 책상보다 크고 럭셔리
   */
  private drawExecutiveDesk(x: number, y: number) {
    // 러그 (바닥 깔개)
    const rug = this.add.rectangle(x, y + 10, 180, 120, 0x7c2d12, 0.3).setOrigin(0.5, 0.5);
    rug.setStrokeStyle(2, 0xfbbf24, 0.5);

    // 책상 (L자 느낌: 메인 + 사이드)
    const main = this.add.rectangle(x, y - 34, 110, 28, 0x44403c).setOrigin(0.5, 0.5);
    main.setStrokeStyle(2, 0xfbbf24, 0.6);
    // 금색 장식 라인
    const trim = this.add.rectangle(x, y - 46, 100, 2, 0xfbbf24).setOrigin(0.5, 0.5);

    // 모니터 2개 (듀얼)
    const mon1 = this.add.rectangle(x - 20, y - 56, 28, 18, 0x0f172a).setOrigin(0.5, 1);
    mon1.setStrokeStyle(1, 0xfbbf24);
    const mon1screen = this.add.rectangle(x - 20, y - 55, 24, 14, 0x1e3a8a).setOrigin(0.5, 1);
    const mon2 = this.add.rectangle(x + 20, y - 56, 28, 18, 0x0f172a).setOrigin(0.5, 1);
    mon2.setStrokeStyle(1, 0xfbbf24);
    const mon2screen = this.add.rectangle(x + 20, y - 55, 24, 14, 0x7c2d12).setOrigin(0.5, 1);

    // 가죽 의자 (왕좌 느낌)
    const throne = this.add.rectangle(x, y + 30, 30, 12, 0x78350f).setOrigin(0.5, 0.5);
    throne.setStrokeStyle(2, 0xfbbf24, 0.8);
    const throneBack = this.add.rectangle(x, y + 16, 30, 6, 0x78350f).setOrigin(0.5, 0.5);
    throneBack.setStrokeStyle(2, 0xfbbf24, 0.8);

    rug.setDepth(0);
    throne.setDepth(1);
    throneBack.setDepth(1);
    main.setDepth(3);
    trim.setDepth(3);
    mon1.setDepth(4);
    mon2.setDepth(4);
    mon1screen.setDepth(4);
    mon2screen.setDepth(4);
  }

  /**
   * 탕비실 — 작은 휴게 공간 (240x240).
   * 냉장고 + 커피머신 + 원형 테이블만 타이트하게 배치.
   */
  private drawPantry() {
    const room = ROOMS.pantry;

    // ── 상단 카운터 (냉장고 + 커피머신) ──
    const counterY = room.y + 55;
    const counter = this.add.rectangle(room.x + room.w / 2, counterY, room.w - 40, 18, 0x78716c).setOrigin(0.5);
    counter.setStrokeStyle(1, 0x44403c);

    // 냉장고 (왼쪽)
    const fridgeX = room.x + 45;
    const fridgeBody = this.add.rectangle(fridgeX, counterY - 18, 28, 50, 0xe2e8f0).setOrigin(0.5, 1);
    fridgeBody.setStrokeStyle(1.5, 0x64748b);
    const fridgeLine = this.add.rectangle(fridgeX, counterY - 40, 26, 1, 0x64748b).setOrigin(0.5);
    const fridgeHandle = this.add.rectangle(fridgeX + 11, counterY - 32, 1.5, 8, 0x334155).setOrigin(0.5);
    const fridgeLabel = this.add.text(fridgeX, counterY - 45, '❄', {
      fontSize: '14px', color: '#0ea5e9',
    }).setOrigin(0.5);

    // 싱크대 (카운터 위 중앙)
    const sinkX = room.x + 105;
    const sink = this.add.rectangle(sinkX, counterY - 2, 22, 10, 0x1e293b).setOrigin(0.5);
    sink.setStrokeStyle(1, 0x64748b);
    const faucet = this.add.rectangle(sinkX, counterY - 8, 1.5, 5, 0x94a3b8).setOrigin(0.5, 1);
    const faucetHead = this.add.rectangle(sinkX + 1.5, counterY - 12, 5, 1.5, 0x94a3b8).setOrigin(0.5);

    // 커피 머신 (오른쪽)
    const coffeeX = room.x + 170;
    const coffeeBody = this.add.rectangle(coffeeX, counterY - 12, 22, 28, 0x1f2937).setOrigin(0.5, 1);
    coffeeBody.setStrokeStyle(1, 0x6b7280);
    const coffeeTop = this.add.rectangle(coffeeX, counterY - 35, 20, 5, 0x374151).setOrigin(0.5);
    const coffeeLED = this.add.circle(coffeeX + 7, counterY - 35, 1, 0xef4444);
    const cup = this.add.ellipse(coffeeX, counterY - 10, 7, 3.5, 0xffffff);
    cup.setStrokeStyle(1, 0x78350f);
    const steam1 = this.add.text(coffeeX - 3, counterY - 18, '~', {
      fontSize: '9px', color: '#cbd5e1',
    }).setOrigin(0.5);
    const steam2 = this.add.text(coffeeX + 3, counterY - 22, '~', {
      fontSize: '9px', color: '#cbd5e1',
    }).setOrigin(0.5);

    // ── 원형 테이블 (하단 중앙) ──
    const tableX = room.x + room.w / 2;
    const tableY = room.y + 170;
    const tableBase = this.add.circle(tableX, tableY, 32, 0x78350f);
    tableBase.setStrokeStyle(2, 0x451a03);
    const tableGloss = this.add.circle(tableX - 7, tableY - 7, 12, 0xffffff, 0.1);
    // 도넛 + 커피잔
    const donut = this.add.circle(tableX - 8, tableY, 4, 0xfb923c);
    donut.setStrokeStyle(1, 0x7c2d12);
    const donutHole = this.add.circle(tableX - 8, tableY, 1.5, 0x44403c);
    const cup1 = this.add.ellipse(tableX + 8, tableY - 4, 6, 3, 0xffffff);
    cup1.setStrokeStyle(1, 0x78350f);
    const cup2 = this.add.ellipse(tableX + 5, tableY + 7, 6, 3, 0xffffff);
    cup2.setStrokeStyle(1, 0x78350f);

    // 의자 4개 (테이블 주변)
    const chairs = [
      [tableX - 42, tableY], [tableX + 42, tableY],
      [tableX, tableY - 42], [tableX, tableY + 42],
    ];
    chairs.forEach(([px, py]) => {
      const c = this.add.circle(px, py, 8, 0xf97316, 0.5);
      c.setStrokeStyle(1.5, 0xfb923c, 0.9);
      c.setDepth(2);
    });

    [counter, fridgeBody, fridgeLine, fridgeHandle, sink, faucet, faucetHead,
     coffeeBody, coffeeTop, coffeeLED, cup, steam1, steam2,
     tableBase, tableGloss, donut, donutHole, cup1, cup2].forEach(o => o && o.setDepth(3));
    fridgeLabel.setDepth(5);
  }

  /**
   * 식물 화분 (포인트) + 천장 전등 분위기.
   */
  private drawPlantsAndLamps() {
    // ── 화분 — 구역 경계 근처에 배치 (벽 대신 시각적 구분 역할) ──
    const plantSpots: Array<[number, number, number]> = [
      // [x, y, scale]
      [40, 248, 1],        // 대표실 좌하단
      [316, 248, 1],       // 대표실 우하단 / 탕비실 경계
      [344, 248, 0.9],     // 탕비실 좌하단
      [580, 248, 1],       // 탕비실 우하단 / 회의실 경계
      [608, 248, 0.9],     // 회의실 좌하단
      [1252, 248, 1],      // 회의실 우하단
      [340, 692, 1.2],     // 코딩 부서 좌하단
      [936, 692, 1.2],     // 코딩 부서 우하단
    ];
    plantSpots.forEach(([x, y, scale]) => this.drawPlant(x, y, scale));

    // ── 천장 전등 ──
    const lampSpots: Array<[number, number, number, number]> = [
      [170, 55, 55, 0xfbbf24],   // 대표실
      [460, 55, 45, 0xf97316],   // 탕비실
      [930, 55, 85, 0x22d3ee],   // 회의실 (넓은 방엔 큰 전등)
      [440, 320, 50, 0xa78bfa],  // 코딩 부서 왼쪽
      [640, 320, 50, 0xa78bfa],
      [840, 320, 50, 0xa78bfa],
    ];
    lampSpots.forEach(([x, y, r, color]) => this.drawLamp(x, y, r, color));
  }

  /**
   * LimeZu 대형 화분 스프라이트 (야자나무 느낌).
   */
  private drawPlant(x: number, y: number, scale: number = 1) {
    const plant = this.add.image(x, y, 'furn_plant_large');
    plant.setScale(2 * scale);
    plant.setOrigin(0.5, 0.8);
    plant.setDepth(5);
  }

  /**
   * 천장 전등 — 원형 발광 원 (Glow). 배경에 은은한 조명감 추가.
   */
  private drawLamp(x: number, y: number, radius: number, color: number) {
    // 바깥 glow (부드럽게 퍼지는)
    const outer = this.add.circle(x, y, radius, color, 0.04);
    // 중간 glow
    const mid = this.add.circle(x, y, radius * 0.6, color, 0.08);
    // 전등 본체
    const lamp = this.add.circle(x, y, 4, 0xfef3c7);
    lamp.setStrokeStyle(1, color);
    // 전등 줄 (천장에서 내려옴)
    const cord = this.add.rectangle(x, y - radius * 0.7, 0.5, radius * 0.7, 0x78716c).setOrigin(0.5, 1);

    outer.setDepth(1);
    mid.setDepth(1);
    cord.setDepth(2);
    lamp.setDepth(2);
  }

  /**
   * 회의실 긴 테이블 + 의자 (크게 — 새 레이아웃 660 너비 활용)
   */
  private drawMeetingTable(x: number, y: number) {
    // 러그
    const rug = this.add.rectangle(x, y + 10, 520, 180, 0x0891b2, 0.08).setOrigin(0.5);
    rug.setStrokeStyle(1, 0x22d3ee, 0.3);

    // 긴 원탁 테이블 (훨씬 크게)
    const table = this.add.rectangle(x, y, 360, 90, 0x44403c).setOrigin(0.5, 0.5);
    table.setStrokeStyle(2, 0x22d3ee, 0.6);
    // 테이블 위 하이라이트
    const gloss = this.add.rectangle(x, y - 20, 320, 4, 0xffffff, 0.15).setOrigin(0.5, 0.5);
    // 테이블 위 노트북 3대
    for (let i = 0; i < 3; i++) {
      const lx = x - 110 + i * 110;
      const lap = this.add.rectangle(lx, y - 5, 28, 18, 0x1e293b).setOrigin(0.5);
      lap.setStrokeStyle(1, 0x475569);
      const scr = this.add.rectangle(lx, y - 5, 24, 14, 0x0f172a).setOrigin(0.5);
      // 화면에 깜빡이는 커서 느낌
      const cursor = this.add.rectangle(lx, y - 5, 1, 8, 0x22d3ee).setOrigin(0.5);
      lap.setDepth(4);
      scr.setDepth(4);
      cursor.setDepth(5);
    }
    // 커피잔 몇 개
    for (let i = 0; i < 4; i++) {
      const cx = x - 150 + i * 100;
      const coffee = this.add.ellipse(cx, y + 25, 8, 4, 0xffffff);
      coffee.setStrokeStyle(1, 0x78350f);
      coffee.setDepth(5);
    }

    // 화이트보드 (위쪽)
    const board = this.add.rectangle(x, y - 70, 220, 38, 0xf1f5f9).setOrigin(0.5, 0.5);
    board.setStrokeStyle(2, 0x22d3ee, 0.7);
    // 화이트보드 위 내용 — 두 줄
    const boardT1 = this.add.text(x, y - 78, 'PROJECT KICK-OFF', {
      fontFamily: 'system-ui',
      fontSize: '11px',
      fontStyle: 'bold',
      color: '#0f172a',
    }).setOrigin(0.5);
    const boardT2 = this.add.text(x, y - 64, '→ Sprint Planning', {
      fontFamily: 'system-ui',
      fontSize: '9px',
      color: '#0891b2',
    }).setOrigin(0.5);

    // 의자 8개 (긴 테이블 둘레)
    const chairs = [
      [x - 140, y + 60], [x - 70, y + 60], [x + 0, y + 60], [x + 70, y + 60], [x + 140, y + 60],
      [x - 140, y - 60], [x + 0, y - 60], [x + 140, y - 60],
    ];
    chairs.forEach(([cx, cy]) => {
      const c = this.add.circle(cx, cy, 10, 0x0e7490, 0.6);
      c.setStrokeStyle(1.5, 0x22d3ee, 0.9);
      c.setDepth(2);
    });

    rug.setDepth(0);
    table.setDepth(3);
    gloss.setDepth(4);
    board.setDepth(2);
    boardT1.setDepth(3);
    boardT2.setDepth(3);
  }

  /**
   * presences의 신원 지문 계산 — slotId/agent/name만 가지고 해시 비슷한 것.
   * 좌표/상태는 포함하지 않아 산책 중에도 재빌드 트리거되지 않는다.
   */
  private computeFingerprint(): string {
    if (!this.presences) return '';
    return this.presences
      .map((p, i) =>
        `${p.slotId}|${p.agent || ''}|${p.colorKey || ''}|${this.slotNames[i] || ''}|${this.slotRoles[i] || ''}`,
      )
      .join('#');
  }

  rebuildAgents() {
    // 기존 스프라이트 완전 제거
    this.agents.forEach((a) => a.container.destroy());
    this.agents.clear();

    if (!this.presences || this.presences.length === 0) {
      this.lastPresenceFingerprint = '';
      return;
    }

    this.presences.forEach((presence, idx) => {
      const pos = this.computePosition(presence, idx);
      const cliKey = (presence.colorKey || presence.agent || 'unknown').toLowerCase();
      const color = CLI_COLORS[cliKey] ?? CLI_COLORS.unknown;
      const name = this.slotNames[idx] || `T${idx + 1}`;
      const roomId = this.resolveRoomId(presence);

      // 루트 컨테이너 (움직임/히트박스)
      const container = this.add.container(pos.x, pos.y);

      // ── LimeZu 스프라이트 캐릭터 ──
      // 10명을 4개 스프라이트로 분배: idx % 4
      const charKey = LIMEZU_CHAR_KEYS[idx % LIMEZU_CHAR_KEYS.length];
      const sprite = this.add.sprite(0, 0, `char_${charKey}_idle`, 0);
      sprite.setScale(LIMEZU_SPRITE_SCALE);
      sprite.setOrigin(0.5, 0.85);  // 발 근처가 컨테이너 중심에 오도록
      sprite.play(`anim_${charKey}_idle`);

      // CLI 색 작은 인디케이터 (머리 위 점) — 어떤 AI인지 표시
      const cliDot = this.add.circle(0, -55, 4, color);
      cliDot.setStrokeStyle(1, 0xffffff, 0.9);

      // 이름 라벨 (캐릭터 아래)
      const label = this.add.text(0, 32, name, {
        fontFamily: 'system-ui',
        fontSize: '11px',
        color: '#ffffff',
        backgroundColor: '#00000088',
        padding: { x: 4, y: 2 },
      }).setOrigin(0.5, 0);

      container.add([sprite, cliDot, label]);
      container.setSize(48, 96);
      // 깊이 5 — 의자(2) 앞, 책상(8) 뒤. 탑다운에서 캐릭터 상체는 책상 위로 나오고
      // 하체는 책상에 가려지는 "앉아있는" 느낌을 낸다.
      container.setDepth(5);
      container.setInteractive(
        new Phaser.Geom.Rectangle(-24, -60, 48, 96),
        Phaser.Geom.Rectangle.Contains,
      );

      container.on('pointerdown', () => this.onDeskClick(presence.slotId));
      container.on('pointerover', () => sprite.setScale(LIMEZU_SPRITE_SCALE * 1.1));
      container.on('pointerout', () => sprite.setScale(LIMEZU_SPRITE_SCALE));

      const state: AgentState = {
        container,
        sprite,
        homeX: pos.x,
        homeY: pos.y,
        targetX: pos.x,
        targetY: pos.y,
        bobPhase: Math.random() * Math.PI * 2,
        typingPhase: Math.random() * Math.PI * 2,
        blinkAt: 2000 + Math.random() * 3000,
        roomId,
        isWalking: false,
        // 대표실/회의실/탕비실도 일단 "책상 앞" 취급 — 코딩 부서만 실제 책상
        isAtDesk: roomId === 'desk',
        lastDecisionAt: 0,
        nextDecisionAt: 2000 + Math.random() * 4000,
      };

      this.agents.set(presence.slotId, state);
    });

    this.lastPresenceFingerprint = this.computeFingerprint();
    this.updateSelectionRing();
  }

  /**
   * 메인 루프 — idle bob + 타이핑 애니메이션 + 눈깜빡임 + 머리 미세 돌림 + walk.
   * 코딩 부서 책상에 앉은 에이전트는 팔이 키보드 위를 교차로 두드림.
   * 모든 에이전트가 주기적으로 눈을 깜빡이고 머리를 살짝 돌린다.
   */
  update(_time: number, delta: number) {
    if (!this.isReady || this.agents.size === 0) return;

    const deltaSec = delta / 1000;

    this.agents.forEach((a) => {
      // ── 이동 tween (Phaser 스프라이트 애니메이션은 내부에서 자동 재생) ──
      const dx = a.targetX - a.container.x;
      const dy = a.targetY - a.container.y;
      const dist = Math.hypot(dx, dy);

      if (dist > 2) {
        const step = Math.min(dist, WALK_SPEED * deltaSec);
        const nx = dx / dist;
        const ny = dy / dist;
        a.container.x += nx * step;
        a.container.y += ny * step;
        a.isWalking = true;
        // 이동 방향에 따라 스프라이트 좌우 플립
        if (a.sprite) {
          if (nx > 0.1) a.sprite.setFlipX(false);
          else if (nx < -0.1) a.sprite.setFlipX(true);
        }
      } else {
        a.container.x = a.targetX;
        a.container.y = a.targetY;
        a.isWalking = false;
      }
    });

    this.updateSelectionRing();
  }

  /**
   * presence.zone을 방 ID로 매핑.
   */
  private resolveRoomId(presence: OfficeAgentPresence): string {
    const zone = (presence.zone || 'desk').toLowerCase();
    if (zone === 'user') return 'user';
    if (zone === 'meeting') return 'meeting';
    return 'desk';
  }

  /**
   * 에이전트가 앉을 자리 좌표. drawFurniture의 책상 배치와 반드시 동기화되어야 한다.
   * - user(대표): 대표실 가죽 의자 앞
   * - meeting: 회의실 테이블 옆
   * - 나머지: 코딩 부서 3x3 그리드의 의자 자리
   */
  private computePosition(presence: OfficeAgentPresence, idx: number): { x: number; y: number } {
    const roomId = this.resolveRoomId(presence);
    if (roomId === 'user') return { x: 170, y: 150 };
    if (roomId === 'meeting') return { x: 930, y: 170 };
    const deskIdx = Math.max(0, idx - 1);
    const col = deskIdx % 3;
    const row = Math.floor(deskIdx / 3);
    return { x: 440 + col * 200, y: 410 + row * 150 };
  }

  private updateSelectionRing() {
    if (!this.selectedRing) return;
    this.selectedRing.clear();
    const agent = this.agents.get(this.selectedDesk);
    if (!agent) return;
    this.selectedRing.lineStyle(3, 0xfacc15, 1);
    this.selectedRing.strokeCircle(agent.container.x, agent.container.y, 26);
  }

  applyProps(props: {
    presences: OfficeAgentPresence[];
    selectedDesk: number;
    slotNames: string[];
    slotRoles: string[];
    onDeskClick: (slotId: number) => void;
  }) {
    this.presences = props.presences;
    this.selectedDesk = props.selectedDesk;
    this.slotNames = props.slotNames;
    this.slotRoles = props.slotRoles;
    this.onDeskClick = props.onDeskClick;

    // 신원 지문이 바뀐 경우에만 재빌드 — 좌표/상태 변경은 update()가 처리
    const newFp = this.computeFingerprint();
    if (newFp !== this.lastPresenceFingerprint) {
      this.rebuildAgents();
    } else {
      this.updateSelectionRing();
    }
  }
}

export default function OfficeCanvas(props: OfficeCanvasProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const gameRef = useRef<Phaser.Game | null>(null);
  const sceneRef = useRef<OfficeScene | null>(null);

  useEffect(() => {
    if (!hostRef.current || gameRef.current) return;

    const scene = new OfficeScene();
    sceneRef.current = scene;

    const game = new Phaser.Game({
      type: Phaser.AUTO,
      parent: hostRef.current,
      width: WORLD_WIDTH,
      height: WORLD_HEIGHT,
      backgroundColor: '#0a0a0f',
      scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
      },
      scene: scene,
      banner: false,
    });

    gameRef.current = game;

    return () => {
      game.destroy(true);
      gameRef.current = null;
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !scene.isReady) {
      if (scene) {
        scene.presences = props.presences;
        scene.selectedDesk = props.selectedDesk;
        scene.slotNames = props.slotNames || [];
        scene.slotRoles = props.slotRoles || [];
        scene.onDeskClick = props.onDeskClick;
      }
      return;
    }
    scene.applyProps({
      presences: props.presences,
      selectedDesk: props.selectedDesk,
      slotNames: props.slotNames || [],
      slotRoles: props.slotRoles || [],
      onDeskClick: props.onDeskClick,
    });
  }, [props.presences, props.selectedDesk, props.slotNames, props.slotRoles, props.onDeskClick]);

  return (
    <div
      ref={hostRef}
      className="w-full h-full bg-[#0a0a0f]"
      data-testid="office-canvas-host"
    />
  );
}
