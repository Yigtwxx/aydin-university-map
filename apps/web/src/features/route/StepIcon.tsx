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
  createLucideIcon,
  type LucideIcon,
} from 'lucide-react';

import type { RouteStep } from '@/features/campus/queries';

/** A flight of stairs and its handrail, lucide-style (lucide has none). */
export const Stairs = createLucideIcon('stairs', [
  ['path', { d: 'M3 20h4.5v-4H12v-4h4.5V8H21', key: 'flight' }],
  ['path', { d: 'M4.5 12.5 19 3.5', key: 'rail' }],
  ['path', { d: 'M7.5 10.6V16', key: 'post-low' }],
  ['path', { d: 'M16.5 5V8', key: 'post-high' }],
]);

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
