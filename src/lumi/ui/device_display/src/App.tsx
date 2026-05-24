import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { StatusBar } from './components/StatusBar';
import { WidgetBar } from './components/WidgetBar';
import { PixelFace } from './components/PixelFace';
import { VectorFace } from './components/VectorFace';
import { TerminalFace } from './components/TerminalFace';
import { SpriteSceneFace } from './components/SpriteSceneFace';
import { SoundVisualizer } from './components/SoundVisualizer';
import { useDeviceState, type FaceStyle, type FaceState } from './state';

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

  return (
    <div
      className="h-full w-full flex items-center justify-center p-4"
      data-theme={device.theme ?? 'default'}
    >
      <motion.div
        layout
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4 }}
        className="w-full max-w-2xl rounded-3xl shadow-2xl overflow-hidden border border-white/20 bg-white/5 backdrop-blur-xl flex flex-col"
        style={{ minHeight: '560px' }}
      >
        <StatusBar
          connected={device.connected}
          statusText={device.statusText}
        />

        <div className="flex-1 flex flex-col items-center justify-center bg-gradient-to-br from-pink-100/10 to-purple-100/10 relative px-6 py-10">
          <AnimatePresence mode="wait">
            <motion.div
              key={style}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ duration: 0.25 }}
              className="flex flex-col items-center gap-4"
            >
              {renderFace(style, state, device.spritePack)}
              {state === 'speak' && style !== 'terminal' && <SoundVisualizer />}
            </motion.div>
          </AnimatePresence>
        </div>

        <WidgetBar
          weather={device.weather}
          cpuPct={device.cpuPct}
        />
      </motion.div>
    </div>
  );
}

function renderFace(style: FaceStyle, state: FaceState, spritePack?: string) {
  switch (style) {
    case 'pixel':    return <PixelFace state={state} />;
    case 'vector':   return <VectorFace state={state} />;
    case 'terminal': return <TerminalFace state={state} />;
    case 'sprite':   return <SpriteSceneFace packName={spritePack ?? 'cat'} />;
  }
}
