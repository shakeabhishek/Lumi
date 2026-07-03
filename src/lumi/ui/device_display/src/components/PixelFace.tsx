import { motion } from 'motion/react';
import type { FaceState } from '../state';

/**
 * The minimalist pixel face the user explicitly chose from the Figma
 * spec: two light-grey rounded squares for eyes, one rounded oblong
 * for the mouth, on a transparent background so the screen card's
 * tinted backdrop shows through.
 *
 * Animations:
 *   IDLE   — slow blink + 1.05× breath pulse
 *   LISTEN — eyes continuously pulse at an alert size + 3-bar waveform
 *            indicator top-left. Originally just a one-time 12% eye-scale
 *            bump with no ongoing motion afterward — indistinguishable
 *            from a frozen face at a glance, unlike every other state
 *            (found in real use, 2026-07-03).
 *   THINK  — eyes shift L↔R + 3-dot indicator top-right
 *   SPEAK  — mouth height pulses on a fast cadence
 */
export function PixelFace({ state }: { state: FaceState }) {
  const eyeAnim = (() => {
    if (state === 'idle') {
      return {
        scaleY: [1, 0.1, 1],
        scale:  [1, 1.05, 1],
      };
    }
    if (state === 'listen') {
      return { scale: [1.12, 1.22, 1.12] };
    }
    if (state === 'think') {
      return { x: [-3, 3, -3] };
    }
    return {};
  })();

  const eyeTransition = (() => {
    if (state === 'idle') return { duration: 3, repeat: Infinity, repeatDelay: 2 };
    if (state === 'think') return { duration: 1.5, repeat: Infinity };
    if (state === 'listen') return { duration: 0.8, repeat: Infinity, ease: 'easeInOut' as const };
    return { duration: 0.3 };
  })();

  const mouthAnim =
    state === 'speak'
      ? { scaleY: [1, 1.5, 0.8, 1.3, 1] }
      : {};
  const mouthTransition =
    state === 'speak' ? { duration: 0.5, repeat: Infinity } : { duration: 0.3 };

  return (
    <div className="relative w-80 h-80 grid grid-cols-8 grid-rows-8 gap-2 p-6">
      {/* Left Eye */}
      <motion.div
        className="col-start-2 row-start-3 col-span-2 row-span-2 bg-white/90 rounded-3xl shadow-sm z-10"
        animate={eyeAnim}
        transition={eyeTransition}
      />

      {/* Right Eye */}
      <motion.div
        className="col-start-6 row-start-3 col-span-2 row-span-2 bg-white/90 rounded-3xl shadow-sm z-10"
        animate={eyeAnim}
        transition={eyeTransition}
      />

      {/* Mouth */}
      <motion.div
        className="col-start-3 row-start-6 col-span-4 row-span-1 bg-white/90 rounded-full shadow-sm z-10"
        animate={mouthAnim}
        transition={mouthTransition}
      />

      {state === 'think' && (
        <motion.div
          className="absolute top-2 right-2 flex gap-1"
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        >
          <div className="w-2 h-2 bg-gray-300 rounded-sm" />
          <div className="w-2 h-2 bg-gray-300 rounded-sm" />
          <div className="w-2 h-2 bg-gray-300 rounded-sm" />
        </motion.div>
      )}

      {/* Listening waveform — 3 bars pulsing at staggered offsets, like a
          live audio level meter, so it reads as "actively picking up
          sound" rather than a static icon. */}
      {state === 'listen' && (
        <div className="absolute top-2 left-2 flex items-end gap-1 h-4">
          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              className="w-1.5 bg-gray-300 rounded-full"
              animate={{ height: ['30%', '100%', '30%'] }}
              transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15, ease: 'easeInOut' }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
