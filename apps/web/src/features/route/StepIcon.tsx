import {
  ArrowUp,
  Building2,
  ArrowUpLeft,
  ArrowUpRight,
  ChevronsDown,
  ChevronsUp,
  CornerUpLeft,
  CornerUpRight,
  Footprints,
  LogIn,
  LogOut,
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
  enter: LogIn,
  exit: LogOut,
  go_to: Footprints,
  stairs_up: ChevronsUp,
  stairs_down: ChevronsDown,
  through: Building2,
};

export function StepIcon({
  turn,
  className,
}: {
  turn: RouteStep['turn'];
  className?: string;
}) {
  // An API newer than this page may send a turn it does not know yet.
  const Icon = ICONS[turn] ?? ArrowUp;
  return <Icon className={className} aria-hidden strokeWidth={2.25} />;
}
