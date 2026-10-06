import {
  ArrowUp,
  ArrowUpLeft,
  ArrowUpRight,
  CornerUpLeft,
  CornerUpRight,
  MapPin,
  Navigation,
  Undo2,
  type LucideIcon,
} from 'lucide-react';

import type { RouteStep } from '@/features/campus/queries';

const ICONS: Record<RouteStep['turn'], LucideIcon> = {
  start: Navigation,
  straight: ArrowUp,
  slight_left: ArrowUpLeft,
  left: CornerUpLeft,
  sharp_left: CornerUpLeft,
  slight_right: ArrowUpRight,
  right: CornerUpRight,
  sharp_right: CornerUpRight,
  u_turn: Undo2,
  arrive: MapPin,
};

export function StepIcon({
  turn,
  className,
}: {
  turn: RouteStep['turn'];
  className?: string;
}) {
  const Icon = ICONS[turn];
  return <Icon className={className} aria-hidden strokeWidth={2.25} />;
}
