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
      className="h-full w-full flex flex-col items-center justify-center p-4 relative overflow-hidden"
      data-theme={device.theme ?? 'default'}
    >
      {state === 'speak' && style !== 'terminal' && <SoundVisualizer />}
      <AudioControls micMuted={device.micMuted} volume={device.volume} brightness={device.brightness} />
      
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
            {renderFace(style, state, device.spritePack)}
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

function renderFace(style: FaceStyle, state: FaceState, spritePack?: string) {
  switch (style) {
    case 'pixel':    return <PixelFace state={state} />;
    case 'vector':   return <VectorFace state={state} />;
    case 'terminal': return <TerminalFace state={state} />;
    case 'sprite':   return <SpriteSceneFace packName={spritePack ?? 'cat'} />;
  }
}
