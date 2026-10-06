'use client';

import { cn } from 'cn';
import {
  animate,
  type AnimationPlaybackControls,
  motion,
  type PanInfo,
  useMotionValue,
  useMotionValueEvent,
} from 'motion/react';
import { useTranslations } from 'next-intl';
import {
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
} from 'react';

import { Glass } from '@/components/glass/Glass';

import {
  coveredHeight,
  cycleSnap,
  lowerSnap,
  pickSnap,
  raiseSnap,
  rubberBand,
  type SheetSnap,
  type SnapHeights,
} from './sheet';

const EASE = [0.2, 0.7, 0.2, 1] as const;
/** A place search with its suggestions showing. */
const OPEN_LIST = '[role="combobox"][aria-expanded="true"]';

interface Props {
  /** Below `md` the panel is a draggable bottom sheet; above, a floating card. */
  sheet: boolean;
  snap: SheetSnap;
  heights: SnapHeights;
  onSnapChange: (snap: SheetSnap) => void;
  /**
   * The height the sheet covers, every frame while it moves (0 on desktop),
   * for map chrome that rides on top of it without re-rendering React.
   */
  onCoveredHeight?: (px: number) => void;
  ready: boolean;
  reducedMotion: boolean;
  /** While a full-screen view sits on top. */
  inert?: boolean;
  /** Brand row and tabs; on the sheet this is where it is dragged. */
  header: ReactNode;
  children: ReactNode;
}

/**
 * The directions/assistant panel. One element in both layouts, so switching
 * between them never remounts the panels (a chat in progress survives).
 *
 * The sheet animates its height rather than sliding a fixed-height box, so
 * whatever sits at its bottom (the assistant's input) stays on screen at every
 * snap and the content scrolls within what is visible.
 */
export function PanelShell({
  sheet,
  snap,
  heights,
  onSnapChange,
  onCoveredHeight,
  ready,
  reducedMotion,
  inert,
  header,
  children,
}: Props) {
  const t = useTranslations('Sheet');
  const bodyId = useId();
  const height = useMotionValue(heights[snap]);
  const animation = useRef<AnimationPlaybackControls | undefined>(undefined);
  /** Height the sheet is settling on; a drag release already started it. */
  const target = useRef(heights[snap]);
  /** Height when the current drag started; `undefined` when not dragging. */
  const dragFrom = useRef<number | undefined>(undefined);
  /** A drag just ended on a button: swallow the click that follows it. */
  const dragged = useRef(false);

  const settle = useCallback(
    (to: SheetSnap, velocity = 0) => {
      target.current = heights[to];
      animation.current?.stop();
      animation.current = animate(
        height,
        heights[to],
        reducedMotion
          ? { duration: 0 }
          : { type: 'spring', velocity, visualDuration: 0.38, bounce: 0.12 },
      );
    },
    [height, heights, reducedMotion],
  );

  // Snaps chosen elsewhere (handle, keys, a new route) and viewport resizes.
  useEffect(() => {
    if (!sheet || dragFrom.current !== undefined) return;
    if (target.current === heights[snap]) return;
    settle(snap);
  }, [sheet, snap, heights, settle]);

  useEffect(() => () => animation.current?.stop(), []);

  const element = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  // The peek shows the top of the content (the route summary and Start, the
  // search): back down there, a list scrolled earlier scrolls back up.
  useEffect(() => {
    if (!sheet || snap !== 'peek' || !body.current) return;
    for (const child of body.current.children)
      if (child.scrollTop > 0)
        child.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' });
  }, [sheet, snap, reducedMotion]);

  useMotionValueEvent(height, 'change', (value) => {
    if (!sheet) return;
    onCoveredHeight?.(coveredHeight(value));
    // An open place list was positioned against where its field was; the
    // field moves with the sheet without scrolling or resizing anything the
    // positioner watches, so nudge it to follow.
    if (element.current?.querySelector(OPEN_LIST))
      window.dispatchEvent(new Event('scroll'));
  });
  useEffect(() => {
    onCoveredHeight?.(sheet ? coveredHeight(height.get()) : 0);
  }, [sheet, height, onCoveredHeight]);

  const onPanStart = () => {
    animation.current?.stop();
    dragFrom.current = height.get();
    dragged.current = true;
  };
  const onPan = (_: PointerEvent, info: PanInfo) => {
    if (dragFrom.current === undefined) return;
    height.set(
      rubberBand(dragFrom.current - info.offset.y, heights.peek, heights.full),
    );
  };
  const onPanEnd = (_: PointerEvent, info: PanInfo) => {
    if (dragFrom.current === undefined) return;
    dragFrom.current = undefined;
    // Momentum: a flick carries on to the next snap, with its speed.
    const velocity = -info.velocity.y;
    const next = pickSnap(height.get(), velocity, heights);
    settle(next, velocity);
    if (next !== snap) onSnapChange(next);
  };
  const pan = sheet ? { onPanStart, onPan, onPanEnd } : {};
  // At peek nothing scrolls, so the whole sheet is a drag surface.
  const bodyPan = sheet && snap === 'peek' ? pan : {};

  const swallowClickAfterDrag = (event: MouseEvent) => {
    if (!dragged.current) return;
    dragged.current = false;
    event.preventDefault();
    event.stopPropagation();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!sheet || event.key !== 'Escape' || event.defaultPrevented) return;
    const from = event.target as HTMLElement;
    // An open place list closes first; the next Escape lowers the sheet.
    if (from.closest(OPEN_LIST)) return;
    if (snap === 'peek') return;
    event.stopPropagation();
    onSnapChange(lowerSnap(snap));
  };

  // Typing needs room for the suggestions above the on-screen keyboard.
  const onFocus = (event: FocusEvent<HTMLElement>) => {
    if (!sheet || snap === 'full') return;
    const field = event.target;
    if (
      (field instanceof HTMLInputElement && field.type !== 'checkbox') ||
      field instanceof HTMLTextAreaElement
    )
      onSnapChange('full');
  };

  const onHandleKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const next =
      event.key === 'ArrowUp'
        ? raiseSnap(snap)
        : event.key === 'ArrowDown'
          ? lowerSnap(snap)
          : undefined;
    if (!next) return;
    event.preventDefault();
    if (next !== snap) onSnapChange(next);
  };

  const handleLabel =
    snap === 'peek'
      ? t('expand')
      : snap === 'half'
        ? t('expandFull')
        : t('collapse');

  return (
    <motion.aside
      ref={element}
      inert={inert}
      data-snap={sheet ? snap : undefined}
      className={cn(
        'pointer-events-none absolute flex flex-col',
        sheet
          ? 'inset-x-2 bottom-2 z-20'
          : 'top-3 bottom-3 left-3 z-10 w-[23.25rem]',
      )}
      style={sheet ? { height } : undefined}
      // The same on the server and the client: with `false` here the client
      // never patched the server's `opacity: 0`, and the panel stayed
      // invisible under reduced motion. MotionConfig drops the movement.
      initial={{ opacity: 0, y: sheet ? 24 : 8 }}
      animate={ready ? { opacity: 1, y: 0 } : undefined}
      transition={{ duration: 0.4, ease: EASE, delay: 0.1 }}
      onKeyDown={onKeyDown}
      onFocus={onFocus}
    >
      <Glass
        variant="thick"
        radius={22}
        refract={false}
        className={cn(
          'pointer-events-auto flex min-h-0 flex-col',
          // viewport-fit=cover: the glass runs under the home indicator, its
          // content (the assistant's input) stays above it.
          sheet ? 'h-full pb-[env(safe-area-inset-bottom)]' : 'max-h-full',
        )}
      >
        <motion.div
          {...pan}
          onPointerDownCapture={() => (dragged.current = false)}
          onClickCapture={swallowClickAfterDrag}
          className={cn('shrink-0', sheet && 'touch-none select-none')}
        >
          {sheet && (
            <button
              type="button"
              aria-label={handleLabel}
              aria-expanded={snap !== 'peek'}
              aria-controls={bodyId}
              onClick={() => onSnapChange(cycleSnap(snap))}
              onKeyDown={onHandleKey}
              className="group flex h-6 w-full cursor-grab items-center justify-center rounded-t-[22px] active:cursor-grabbing"
            >
              <span
                aria-hidden
                className="h-[5px] w-9 rounded-full bg-ink/18 transition-colors duration-150 ease-out-soft group-hover:bg-ink/30 dark:bg-white/22 dark:group-hover:bg-white/35"
              />
            </button>
          )}
          {header}
        </motion.div>
        <motion.div
          ref={body}
          id={bodyId}
          {...bodyPan}
          onPointerDownCapture={() => (dragged.current = false)}
          onClickCapture={swallowClickAfterDrag}
          className={cn(
            'flex min-h-0 flex-1 flex-col',
            sheet && snap === 'peek' && 'touch-none',
          )}
        >
          {children}
        </motion.div>
      </Glass>
    </motion.aside>
  );
}
