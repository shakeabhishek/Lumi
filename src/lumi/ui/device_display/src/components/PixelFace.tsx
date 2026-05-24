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
 *   LISTEN — eyes hold slightly larger (alert pose)
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
      return { scale: 1.12 };
    }
    if (state === 'think') {
      return { x: [-3, 3, -3] };
    }
    return {};
  })();

  const eyeTransition = (() => {
    if (state === 'idle') return { duration: 3, repeat: Infinity, repeatDelay: 2 };
    if (state === 'think') return { duration: 1.5, repeat: Infinity };
    if (state === 'listen') return { duration: 0.4 };
    return { duration: 0.3 };
  })();

  const mouthAnim =
    state === 'speak'
      ? { scaleY: [1, 1.5, 0.8, 1.3, 1] }
      : {};
  const mouthTransition =
    state === 'speak' ? { duration: 0.5, repeat: Infinity } : { duration: 0.3 };

  return (
    <div className="relative w-56 h-56 grid grid-cols-8 grid-rows-8 gap-1 p-4">
      <motion.div
        className="col-start-2 row-start-3 col-span-2 row-span-2 bg-gray-200/95 rounded-md shadow-sm"
        animate={eyeAnim}
        transition={eyeTransition}
      />
      <motion.div
        className="col-start-5 row-start-3 col-span-2 row-span-2 bg-gray-200/95 rounded-md shadow-sm"
        animate={eyeAnim}
        transition={eyeTransition}
      />
      <motion.div
        className="col-start-2 row-start-6 col-span-5 row-span-1 bg-gray-200/95 rounded-full shadow-sm"
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
    </div>
  );
}
