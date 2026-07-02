import { AnimatePresence, motion } from 'motion/react';
import type { Caption } from '../state';

interface CaptionBubbleProps {
  caption: Caption | null;
}

// Ephemeral, current-turn-only speech bubble — what Lumi heard (user,
// neutral/white) and what it's saying (lumi, warm amber), not a scrolling
// chat log. Clears on IDLE (see main.py's clear_caption() call). Backend
// sends ONE sentence at a time (not the cumulative reply) so a long,
// multi-sentence answer doesn't grow the bubble to fill the screen.
export function CaptionBubble({ caption }: CaptionBubbleProps) {
  return (
    <div className="absolute bottom-40 inset-x-0 flex justify-center z-20 pointer-events-none px-8">
      <AnimatePresence mode="wait">
        {caption && caption.text && (
          <motion.div
            // Keying on speaker+text (not just speaker) so each new
            // sentence from the SAME speaker still gets a fresh
            // enter/exit crossfade, instead of the text abruptly
            // snapping mid-element as Lumi's reply streams sentence by
            // sentence.
            key={`${caption.speaker}:${caption.text}`}
            initial={{ opacity: 0, y: 12, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.96 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
            className={`max-w-lg rounded-3xl px-6 py-3 backdrop-blur-md border shadow-xl text-center text-lg leading-snug ${
              caption.speaker === 'user'
                ? 'bg-white/10 border-white/20 text-white/90'
                : 'bg-amber-400/15 border-amber-300/30 text-amber-50'
            }`}
          >
            {caption.text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
