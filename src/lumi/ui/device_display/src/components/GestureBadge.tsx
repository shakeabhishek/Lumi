import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import type { Gesture, GestureKind } from '../state';

interface GestureBadgeProps {
  gesture: Gesture | null;
}

const GESTURE_STYLE: Record<GestureKind, { emoji: string; ring: string }> = {
  // Also the one gesture that actually wakes Lumi (see FileTriggerWake in
  // audio/wake_word.py) — PixelFace handles its own smile+dance reaction
  // separately, this badge still shows for consistency with the rest.
  wave: { emoji: '👋', ring: 'ring-amber-300/60' },
  // "I hear you" pause cue — display reaction only in this build, not
  // wired to interrupt TTS playback. Natural future hook is
  // audio/tts.py's speak_streaming(..., on_sentence=...) callback, not
  // built now (needs its own design pass for what happens to
  // already-synthesized-but-unplayed audio).
  open_palm: { emoji: '✋', ring: 'ring-white/50' },
  thumbs_up: { emoji: '✅', ring: 'ring-emerald-400/70' },
  thumbs_down: { emoji: '❌', ring: 'ring-rose-400/70' },
  fist: { emoji: '✊', ring: 'ring-neutral-400/60' },
};

const VISIBLE_MS = 1200;

// A gesture is an inherently transient, one-shot flash (unlike
// CaptionBubble, which persists until the backend explicitly clears it
// on IDLE) — there's no /gesture/clear push from the backend, so this
// self-clears client-side instead.
export function GestureBadge({ gesture }: GestureBadgeProps) {
  const [visible, setVisible] = useState(false);

  // Keyed on gesture?.ts (a primitive), not the gesture object itself:
  // DeviceBus.publish() rebroadcasts the FULL merged snapshot on every
  // publish (see device_bus.py), including unrelated background ticks
  // like cpu_sampler every 5s — each SSE message is freshly
  // JSON.parse()'d, so a same-content `gesture` object gets a new
  // reference every time even when nothing about it changed. Depending
  // on the object itself would restart this timer on every unrelated
  // tick and the badge would never actually self-clear.
  useEffect(() => {
    if (gesture == null) return;
    setVisible(true);
    const t = setTimeout(() => setVisible(false), VISIBLE_MS);
    return () => clearTimeout(t);
  }, [gesture?.ts]);

  const style = gesture ? GESTURE_STYLE[gesture.type] : null;

  return (
    <div className="absolute top-24 inset-x-0 flex justify-center z-20 pointer-events-none">
      <AnimatePresence mode="wait">
        {visible && gesture && style && (
          <motion.div
            key={`${gesture.type}:${gesture.ts}`}
            initial={{ opacity: 0, y: -12, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.9 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
            className={`flex items-center justify-center w-16 h-16 rounded-full bg-black/30 backdrop-blur-md border shadow-xl text-3xl ring-4 ${style.ring}`}
          >
            {style.emoji}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
