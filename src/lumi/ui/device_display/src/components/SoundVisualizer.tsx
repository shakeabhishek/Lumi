import { motion } from 'motion/react';

/**
 * Twelve gradient bars that pulse while Lumi is speaking. Lifted from
 * the Figma export and slightly toned down (warmer pink → purple, no
 * neon). Renders below the face area only during the SPEAK state.
 */
export function SoundVisualizer() {
  return (
    <div className="flex items-end justify-center gap-1 h-12 mt-2">
      {Array.from({ length: 12 }).map((_, i) => (
        <motion.div
          key={i}
          className="w-1.5 bg-gradient-to-t from-pink-500 to-purple-500 rounded-full"
          animate={{ height: ['20%', '100%', '40%', '80%', '30%'] }}
          transition={{
            duration: 0.6,
            repeat: Infinity,
            delay: i * 0.04,
            ease: 'easeInOut',
          }}
        />
      ))}
    </div>
  );
}
