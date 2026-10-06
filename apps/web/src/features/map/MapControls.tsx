'use client';

import { cn } from 'cn';
import { Earth, Minus, Plus, ScanSearch } from 'lucide-react';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';

import { Glass } from '@/components/glass/Glass';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import { POLAR_3D, POLAR_TOP_DOWN, useCameraStore } from './cameraStore';

const ZOOM_IN = 0.25;
/** Google's photorealistic tiles need the Cesium ion token at build time. */
const PHOTOREAL_AVAILABLE = Boolean(process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN);
const ZOOM_OUT = -0.33;

/** Compass, zoom, 2D/3D and fit as one slim glass column. */
export function MapControls({ reducedMotion }: { reducedMotion: boolean }) {
  const t = useTranslations('Map');
  const {
    controls,
    headingDeg,
    topDown,
    setTopDown,
    requestFit,
    photoreal,
    setPhotoreal,
  } = useCameraStore();
  const animate = !reducedMotion;

  return (
    <Glass
      radius={14}
      className="pointer-events-auto flex w-10 flex-col items-stretch py-0.5"
    >
      <ControlButton
        label={t('north')}
        onClick={() => void controls?.rotateAzimuthTo(0, animate)}
      >
        <svg
          viewBox="0 0 24 24"
          className="size-6"
          style={{ transform: `rotate(${-headingDeg}deg)` }}
          aria-hidden
        >
          <path d="M12 3.2 14.9 12H9.1Z" fill="var(--brick)" />
          <path d="M12 20.8 9.1 12h5.8Z" fill="currentColor" opacity=".28" />
          <circle cx="12" cy="12" r="1.3" fill="var(--stone-raised)" />
        </svg>
      </ControlButton>
      <Divider />
      {/* Touch screens pinch to zoom; the buttons are for mouse and keyboard. */}
      <div className="hidden flex-col md:flex">
        <ControlButton
          label={t('zoomIn')}
          onClick={() =>
            void controls?.dolly(controls.distance * ZOOM_IN, animate)
          }
        >
          <Plus className="size-4.5" strokeWidth={2} />
        </ControlButton>
        <ControlButton
          label={t('zoomOut')}
          onClick={() =>
            void controls?.dolly(controls.distance * ZOOM_OUT, animate)
          }
        >
          <Minus className="size-4.5" strokeWidth={2} />
        </ControlButton>
        <Divider />
      </div>
      <ControlButton
        // The visible "2D"/"3D" leads the name, so voice control matches it.
        label={topDown ? `3D: ${t('view3d')}` : `2D: ${t('view2d')}`}
        pressed={topDown}
        onClick={() => {
          void controls?.rotatePolarTo(
            topDown ? POLAR_3D : POLAR_TOP_DOWN,
            animate,
          );
          setTopDown(!topDown);
        }}
        className="text-xs font-semibold tracking-heading"
      >
        {topDown ? '3D' : '2D'}
      </ControlButton>
      <ControlButton label={t('fit')} onClick={requestFit}>
        <ScanSearch className="size-4.5" strokeWidth={1.75} />
      </ControlButton>
      {PHOTOREAL_AVAILABLE && (
        <>
          <Divider />
          <ControlButton
            label={photoreal ? t('drawnView') : t('photorealView')}
            pressed={photoreal}
            onClick={() => setPhotoreal(!photoreal)}
            className={photoreal ? 'text-route' : undefined}
          >
            <Earth className="size-4.5" strokeWidth={1.75} />
          </ControlButton>
        </>
      )}
    </Glass>
  );
}

function Divider() {
  return <span aria-hidden className="mx-2.5 my-0.5 h-px bg-hairline" />;
}

function ControlButton({
  label,
  onClick,
  className,
  pressed,
  children,
}: {
  label: string;
  onClick: () => void;
  className?: string;
  pressed?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            onClick={onClick}
            aria-label={label}
            aria-pressed={pressed}
            className={cn(
              'mx-0.5 flex h-9 items-center justify-center rounded-[10px] text-ink transition-colors duration-150 ease-out-soft hover:bg-fill-strong active:bg-fill-strong',
              className,
            )}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="left" sideOffset={10}>
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
