'use client';

import { Minus, Plus, ScanSearch } from 'lucide-react';
import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';

import { Glass } from '@/components/glass/Glass';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import { POLAR_3D, POLAR_TOP_DOWN, useCameraStore } from './cameraStore';

const ZOOM_IN = 0.38;
const ZOOM_OUT = -0.6;

export function MapControls({ reducedMotion }: { reducedMotion: boolean }) {
  const t = useTranslations('Map');
  const { controls, headingDeg, topDown, setTopDown, requestFit } =
    useCameraStore();
  const animate = !reducedMotion;

  return (
    <div className="pointer-events-auto flex flex-col items-center gap-2.5">
      <Glass radius={999} className="size-12">
        <ControlButton
          label={t('north')}
          onClick={() => void controls?.rotateAzimuthTo(0, animate)}
          className="size-12 rounded-full"
        >
          <svg
            viewBox="0 0 24 24"
            className="size-7 transition-transform duration-75"
            style={{ transform: `rotate(${-headingDeg}deg)` }}
            aria-hidden
          >
            <path d="M12 2.5 15.2 12H8.8Z" fill="var(--brick)" />
            <path d="M12 21.5 8.8 12h6.4Z" fill="currentColor" opacity=".35" />
            <text
              x="12"
              y="13.6"
              textAnchor="middle"
              fontSize="4.6"
              fontWeight="700"
              fill="var(--stone-raised)"
              className="font-display"
            >
              {t('northLetter')}
            </text>
          </svg>
        </ControlButton>
      </Glass>

      <Glass radius={16} className="flex w-12 flex-col">
        <ControlButton
          label={t('zoomIn')}
          onClick={() =>
            void controls?.dolly(controls.distance * ZOOM_IN, animate)
          }
          className="h-11 w-12 rounded-t-2xl"
        >
          <Plus className="size-5" />
        </ControlButton>
        <span aria-hidden className="mx-3 h-px bg-hairline" />
        <ControlButton
          label={t('zoomOut')}
          onClick={() =>
            void controls?.dolly(controls.distance * ZOOM_OUT, animate)
          }
          className="h-11 w-12 rounded-b-2xl"
        >
          <Minus className="size-5" />
        </ControlButton>
      </Glass>

      <Glass radius={16} className="flex w-12 flex-col">
        <ControlButton
          label={topDown ? t('view3d') : t('view2d')}
          pressed={topDown}
          onClick={() => {
            void controls?.rotatePolarTo(
              topDown ? POLAR_3D : POLAR_TOP_DOWN,
              animate,
            );
            setTopDown(!topDown);
          }}
          className="h-11 w-12 rounded-t-2xl font-display text-md font-bold"
        >
          {topDown ? '3D' : '2D'}
        </ControlButton>
        <span aria-hidden className="mx-3 h-px bg-hairline" />
        <ControlButton
          label={t('fit')}
          onClick={requestFit}
          className="h-11 w-12 rounded-b-2xl"
        >
          <ScanSearch className="size-5" />
        </ControlButton>
      </Glass>
    </div>
  );
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
            className={[
              'flex items-center justify-center text-ink transition-colors duration-150 ease-out-soft hover:bg-accent active:bg-accent',
              className ?? '',
            ].join(' ')}
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
