import { useState, useEffect } from 'react';
import { motion } from 'motion/react';
import { 
  Settings, 
  Bell, 
  Lightbulb, 
  Camera, 
  Timer,
  Wifi,
  Sun,
  Cloud,
  CloudRain,
  CloudSnow
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

  const getWeatherIcon = (condition?: WeatherSnapshot['condition']) => {
    switch (condition) {
      case 'sunny':       return <Sun className="w-6 h-6 text-yellow-400" />;
      case 'clear-night': return <Sun className="w-6 h-6 text-indigo-200" />; // using sun as fallback for clear
      case 'cloudy':      return <Cloud className="w-6 h-6 text-gray-300" />;
      case 'rainy':       return <CloudRain className="w-6 h-6 text-blue-400" />;
      case 'snowy':       return <CloudSnow className="w-6 h-6 text-cyan-200" />;
      default:            return <Cloud className="w-6 h-6 text-white/30" />;
    }
  };

  return (
    <div className="absolute right-0 top-0 bottom-0 w-80 p-8 flex flex-col items-end justify-between z-20">
      
      {/* Top Section: Settings, Notifications, Wifi */}
      <div className="flex gap-4 w-full justify-end items-center">
        <div className="h-20 px-8 rounded-full bg-white/10 border border-white/10 backdrop-blur-md flex items-center justify-center gap-4 text-white/70 shadow-sm shrink-0">
          <Wifi size={36} />
          <span className="font-medium text-lg tracking-wide">TheKrustyKrab</span>
        </div>
        <motion.button 
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
          className="w-20 h-20 shrink-0 rounded-full bg-white/10 border border-white/10 backdrop-blur-md flex items-center justify-center text-white/70 hover:bg-white/20 hover:text-white transition-colors relative"
        >
          <Bell size={36} />
          {/* Notification Dot */}
          <div className="absolute top-4 right-4 w-3 h-3 bg-pink-500 rounded-full" />
        </motion.button>
        <motion.button 
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
          className="w-20 h-20 shrink-0 rounded-full bg-white/10 border border-white/10 backdrop-blur-md flex items-center justify-center text-white/70 hover:bg-white/20 hover:text-white transition-colors"
        >
          <Settings size={36} />
        </motion.button>
      </div>

      <div className="flex-1" />

      {/* Middle Section: Massive Clock & Weather */}
      <div className="flex flex-col items-end text-right">
        <h1 className="text-8xl font-light text-white tracking-tighter drop-shadow-lg mb-2">
          {formatTime(time).replace(/ AM| PM/, '')}
        </h1>
        <div className="flex items-center gap-4 text-white/80 font-medium text-2xl tracking-wide">
          <span>{formatDate(time)}</span>
        </div>
        {weather && (
          <div className="flex items-center gap-3 mt-6 bg-white/5 px-6 py-3 rounded-3xl border border-white/10 backdrop-blur-md shadow-xl">
            {getWeatherIcon(weather.condition)}
            <span className="text-2xl font-light text-white">
              {Math.round(weather.tempC)}°C <span className="capitalize">{weather.condition}</span>
            </span>
          </div>
        )}
      </div>

      <div className="flex-1" />

      {/* Bottom Section: OpenClaw Skills / Action Buttons */}
      <div className="flex flex-col gap-4 w-full">
        <h3 className="text-white/40 text-sm font-medium tracking-widest uppercase text-right mb-2 pr-2">Quick Actions</h3>
        <div className="flex flex-col gap-4 w-full items-end">
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
