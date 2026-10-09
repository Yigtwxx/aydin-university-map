import { cn } from 'cn';
import {
  Banknote,
  BookOpen,
  Coffee,
  ConciergeBell,
  Cross,
  DoorClosed,
  DoorOpen,
  Dumbbell,
  GraduationCap,
  type LucideIcon,
  ShoppingBag,
  SquareParking,
  Trees,
  Utensils,
} from 'lucide-react';
import type { HTMLAttributes } from 'react';

import type { PlaceCategory, PoiCategory } from './places';

/** Glyphs of the quick-filter chips (blocks wear their letter instead). */
export const CATEGORY_ICONS: Record<
  Exclude<PlaceCategory, 'blocks'>,
  LucideIcon
> = {
  gates: DoorOpen,
  health: Cross,
  library: BookOpen,
  eat: Utensils,
  shop: ShoppingBag,
  services: ConciergeBell,
  outdoor: Trees,
  rooms: DoorClosed,
};

/** A business's own glyph: a café is a cup even under "Eat & drink". */
export const POI_ICONS: Record<PoiCategory, LucideIcon> = {
  food: Utensils,
  cafe: Coffee,
  shop: ShoppingBag,
  health: Cross,
  library: BookOpen,
  student_services: GraduationCap,
  atm: Banknote,
  sports: Dumbbell,
  parking: SquareParking,
  service: ConciergeBell,
};

/**
 * Pin colours, one per kind of errand. They stay clear of the interface's
 * own signals (route blue, destination brick, campus ochre), carry a white
 * glyph at 3:1 or better, and keep their white ring on the drawn map and on
 * photoreal tiles, by day and by night, so one value serves both themes.
 */
export const POI_COLORS: Record<PoiCategory, string> = {
  food: '#e0701a',
  cafe: '#e0701a',
  shop: '#8257e6',
  health: '#d93a6c',
  library: '#0f8c82',
  student_services: '#5e6b80',
  atm: '#5e6b80',
  sports: '#2f9a57',
  parking: '#5e6b80',
  service: '#5e6b80',
};

/**
 * A pressed quick-filter chip lights up in its category's colour: the pin
 * colour of its businesses, a block badge's tone, the ochre of the entrance
 * rims, the green of the campus planting. Pin colours are deepened a little
 * so white letters keep 4.5:1. Rooms have no colour of their own and stay ink.
 */
export const CHIP_COLORS: Record<PlaceCategory, { bg: string; fg: string }> = {
  blocks: { bg: 'var(--block-main)', fg: '#fff' },
  gates: { bg: 'var(--ochre)', fg: 'var(--ochre-ink)' },
  health: { bg: deepen(POI_COLORS.health), fg: '#fff' },
  library: { bg: deepen(POI_COLORS.library), fg: '#fff' },
  eat: { bg: deepen(POI_COLORS.food), fg: '#fff' },
  shop: { bg: deepen(POI_COLORS.shop), fg: '#fff' },
  services: { bg: deepen(POI_COLORS.service), fg: '#fff' },
  outdoor: { bg: 'var(--plane)', fg: '#fff' },
  rooms: { bg: 'var(--ink)', fg: 'var(--stone-raised)' },
};

function deepen(color: string): string {
  return `color-mix(in oklab, ${color} 85%, black)`;
}

/**
 * A business's glyph, white on its category colour: the face of its map pin,
 * and its badge on photo tiles and in lists.
 */
export function PoiBadge({
  category,
  className,
  iconClassName,
  style,
  ...rest
}: {
  category: PoiCategory;
  iconClassName?: string;
} & HTMLAttributes<HTMLSpanElement>) {
  const Icon = POI_ICONS[category];
  return (
    <span
      aria-hidden
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full text-white',
        className,
      )}
      style={{ backgroundColor: POI_COLORS[category], ...style }}
      {...rest}
    >
      <Icon className={cn('size-3.5', iconClassName)} strokeWidth={2.25} />
    </span>
  );
}
