import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { WidgetBar } from './components/WidgetBar';
import { PixelFace } from './components/PixelFace';
import { VectorFace } from './components/VectorFace';
import { TerminalFace } from './components/TerminalFace';
import { SpriteSceneFace } from './components/SpriteSceneFace';
import { SoundVisualizer } from './components/SoundVisualizer';
import { AudioControls } from './components/AudioControls';
import { RightPanel } from './components/RightPanel';
import { AmbientBackground } from './components/AmbientBackground';
import { CaptionBubble } from './components/CaptionBubble';
import { GestureBadge } from './components/GestureBadge';
import { useDeviceState, type FaceStyle, type FaceState } from './state';
import { Camera } from 'lucide-react';

export function App() {
  const device = useDeviceState();
  const [demoState, setDemoState] = useState<FaceState>('idle');

  // Until the backend SSE stream is live, cycle states locally so we can
  // verify all four visuals render. Once /device-display/events is
  // emitting real LumiState transitions, this auto-cycle goes away.
  useEffect(() => {
    if (device.connected) return;
    const interval = setInterval(() => {
      const order: FaceState[] = ['idle', 'listen', 'think', 'speak'];
      setDemoState((s) => order[(order.indexOf(s) + 1) % order.length]);
    }, 3500);
    return () => clearInterval(interval);
  }, [device.connected]);

  const state = device.connected ? device.state : demoState;
  const style: FaceStyle = device.style ?? 'pixel';
  // `presence == null` means no real reading has arrived yet (nothing's
  // wrong — treat as present so a fresh boot doesn't start "asleep").
  // Gated to IDLE only so a turn in progress never gets visually
  // interrupted by someone stepping away mid-conversation. Presence no
  // longer wakes Lumi (only a wave gesture or the wake word does — see
  // audio/wake_word.py) — it now only drives this display-only sleep
  // treatment.
  const sleeping = device.presence?.present === false && state === 'idle';

  return (
    <div
      className="h-full w-full flex flex-col items-center justify-center p-4 relative overflow-hidden bg-[#0a0a0a]"
      data-theme={device.theme ?? 'default'}
    >
      <AmbientBackground />
      {state === 'speak' && style !== 'terminal' && <SoundVisualizer />}
      <AudioControls micMuted={device.micMuted} volume={device.volume} brightness={device.brightness} />
      <CaptionBubble caption={device.caption} />
      <GestureBadge gesture={device.gesture} />

      {/* Camera-active indicator — on-screen substitute for the physical
          NeoPixel privacy light (no LED-driving code exists yet, see
          CLAUDE.md's "Camera & vision" privacy-by-design section).
          Reflects the vision-worker's presence heartbeat via
          vision_liveness_sampler, not a local flag — goes dark within
          ~12s of the worker actually stopping (camera_enabled off, or
          the process down). */}
      {device.cameraActive && (
        <div className="absolute top-4 left-4 z-20 flex items-center gap-1.5 pointer-events-none">
          <motion.div
            animate={{ opacity: [0.5, 1, 0.5] }}
            transition={{ duration: 2, repeat: Infinity }}
          >
            <Camera className="w-4 h-4 text-rose-400" />
          </motion.div>
        </div>
      )}

      {/* Presence-driven ambient dim, paired with the face's own closed-
          eyes/Zzz treatment (PixelFace) or sleeping glyph/status
          (VectorFace/TerminalFace) below — a subtle dim rather than the
          face carrying the whole "asleep" signal alone. */}
      {sleeping && (
        <motion.div
          className="absolute inset-0 bg-black/30 z-30 pointer-events-none"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 1.5 }}
        />
      )}

      {/* Sprite scenes are pre-rendered PNG loops with no "eyes" to
          close, so they get a standalone Zzz overlay instead of the
          per-face treatment PixelFace/VectorFace/TerminalFace render
          themselves below. */}
      {sleeping && style === 'sprite' && (
        <motion.div
          className="absolute top-1/3 right-1/3 text-3xl font-bold text-white/70 select-none z-30 pointer-events-none"
          animate={{ y: [0, -14], opacity: [0, 1, 0] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
        >
          Zzz
        </motion.div>
      )}

      {/* Center Face (Perfectly Centered) */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
        <AnimatePresence mode="wait">
          <motion.div
            key={style}
            initial={{ opacity: 0, scale: 1.15 }}
            animate={{ opacity: 1, scale: 1.25 }}
            exit={{ opacity: 0, scale: 1.15 }}
            transition={{ duration: 0.25 }}
            className="flex flex-col items-center gap-12 cursor-pointer pointer-events-auto origin-center"
            whileTap={{ scale: 1.15, rotate: -2 }}
          >
            {renderFace(
              style,
              state,
              device.spritePack,
              device.gesture?.type === 'wave' ? device.gesture.ts : null,
              sleeping,
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Bottom Metrics Tiles */}
      <div className="absolute bottom-12 inset-x-0 flex justify-center z-20 pointer-events-none">
        <div className="w-full max-w-2xl px-8 pointer-events-auto">
          <WidgetBar
            cpuPct={device.cpuPct}
            memPct={device.memPct}
            cpuTempC={device.cpuTempC}
          />
        </div>
      </div>

      <RightPanel weather={device.weather} />
    </div>
  );
}

function renderFace(
  style: FaceStyle,
  state: FaceState,
  spritePack?: string,
  waveAt?: number | null,
  sleeping?: boolean,
) {
  switch (style) {
    case 'pixel':    return <PixelFace state={state} waveAt={waveAt} sleeping={sleeping} />;
    case 'vector':   return <VectorFace state={state} sleeping={sleeping} />;
    case 'terminal': return <TerminalFace state={state} sleeping={sleeping} />;
    // Sprite scenes are pre-rendered PNG loops with no programmatic
    // "face" to close — the dim + Zzz overlay above still communicates
    // sleep without needing per-scene authoring.
    case 'sprite':   return <SpriteSceneFace packName={spritePack ?? 'cat'} />;
  }
}
