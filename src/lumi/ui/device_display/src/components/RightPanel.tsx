import { useState, useEffect } from 'react';
import { motion } from 'motion/react';
import { 
  Settings, 
  Bell, 
  Lightbulb, 
  Camera, 
  Timer,
  Cloud,
  Sun,
  CloudRain
} from 'lucide-react';

import type { WeatherSnapshot } from '../state';

interface RightPanelProps {
  weather?: WeatherSnapshot | null;
}

export function RightPanel({ weather }: RightPanelProps) {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  };

  const formatDate = (date: Date) => {
    return date.toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
    });
  };

  // Parse weather string to pick an icon (super simple heuristic)
  const getWeatherIcon = (w: WeatherSnapshot['condition']) => {
    switch (w) {
      case 'sunny': return <Sun size={32} className="text-yellow-400" />;
      case 'rainy': return <CloudRain size={32} className="text-blue-400" />;
      case 'snowy': return <CloudRain size={32} className="text-blue-200" />;
      default: return <Cloud size={32} className="text-white/70" />;
    }
  };

  return (
    <div className="absolute right-8 top-0 bottom-0 py-8 flex flex-col items-end justify-between z-20">
      
      {/* Top Section: Settings & Notifications */}
      <div className="flex gap-4">
        <motion.button 
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
          className="w-12 h-12 rounded-full bg-white/5 border border-white/10 backdrop-blur-md flex items-center justify-center text-white/70 hover:bg-white/10 hover:text-white transition-colors relative"
        >
          <Bell size={24} />
          {/* Notification Dot */}
          <div className="absolute top-3 right-3 w-2 h-2 bg-pink-500 rounded-full" />
        </motion.button>
        <motion.button 
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
          className="w-12 h-12 rounded-full bg-white/5 border border-white/10 backdrop-blur-md flex items-center justify-center text-white/70 hover:bg-white/10 hover:text-white transition-colors"
        >
          <Settings size={24} />
        </motion.button>
      </div>

      {/* Middle Section: Massive Clock & Weather */}
      <div className="flex flex-col items-end text-right mt-12">
        <h1 className="text-8xl font-light text-white tracking-tighter drop-shadow-lg mb-2">
          {formatTime(time).replace(/ AM| PM/, '')}
        </h1>
        <div className="flex items-center gap-4 text-white/80 font-medium text-2xl tracking-wide">
          <span>{formatDate(time)}</span>
        </div>
        
        {/* Weather Sub-widget */}
        {weather && (
          <div className="flex items-center gap-3 mt-6 bg-white/5 px-6 py-3 rounded-3xl border border-white/10 backdrop-blur-md shadow-xl">
            {getWeatherIcon(weather.condition)}
            <span className="text-2xl font-light text-white">
              {weather.tempC}°C {weather.condition}
            </span>
          </div>
        )}
      </div>

      <div className="flex-1" />

      {/* Bottom Section: OpenClaw Skills / Action Buttons */}
      <div className="flex flex-col gap-4">
        <h3 className="text-white/40 text-sm font-medium tracking-widest uppercase text-right mb-2 pr-2">Quick Actions</h3>
        <div className="flex flex-col gap-4">
          <ActionButton icon={<Lightbulb size={24} />} label="Room Lights" active />
          <ActionButton icon={<Camera size={24} />} label="Vision Mode" />
          <ActionButton icon={<Timer size={24} />} label="Set Timer" />
        </div>
      </div>
    </div>
  );
}

function ActionButton({ icon, label, active = false }: { icon: React.ReactNode, label: string, active?: boolean }) {
  return (
    <motion.button
      whileHover={{ scale: 1.05, x: -5 }}
      whileTap={{ scale: 0.95 }}
      className={`flex items-center justify-end gap-4 px-6 py-4 rounded-3xl backdrop-blur-md border transition-colors w-56
        ${active 
          ? 'bg-white/20 border-white/40 text-white shadow-lg' 
          : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10 hover:text-white'
        }
      `}
    >
      <span className="font-medium text-lg">{label}</span>
      <div className={`p-2 rounded-full flex items-center justify-center ${active ? 'bg-white/20 text-white' : 'bg-black/20 text-white/70'}`}>
        {icon}
      </div>
    </motion.button>
  );
}
