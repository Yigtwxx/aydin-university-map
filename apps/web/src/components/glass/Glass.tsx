'use client';

/**
 * Liquid-glass surface. The refraction filter is adapted from React Bits'
 * GlassSurface (https://reactbits.dev, MIT + Commons Clause): an SVG
 * displacement map bends the backdrop at the edges and splits it slightly per
 * colour channel. Only Chromium applies SVG filters in `backdrop-filter`;
 * elsewhere the `.glass` class keeps a frosted look with the same tint and
 * edge light, so the layout never depends on the effect.
 */

import { cn } from 'cn';
import {
  type ComponentPropsWithoutRef,
  type ElementType,
  type Ref,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';

export type GlassVariant = 'regular' | 'thick' | 'tint';

/** Mirrors `--glass-blur` in globals.css, so both paths frost the same. */
const BLUR_PX: Record<GlassVariant, number> = {
  regular: 24,
  thick: 40,
  tint: 16,
};

/**
 * Edge lensing strength. Kept low: the bend should read as a thick pane
 * catching light, not as a visual effect. Thick panels carry text, so they
 * bend least.
 */
const DISTORTION: Record<GlassVariant, number> = {
  regular: -56,
  thick: -32,
  tint: -72,
};

type GlassProps<T extends ElementType> = {
  as?: T;
  variant?: GlassVariant;
  /** Corner radius in px; the displacement map follows it. */
  radius?: number;
  refract?: boolean;
  ref?: Ref<HTMLElement>;
} & Omit<ComponentPropsWithoutRef<T>, 'as'>;

let refractionSupport: boolean | undefined;

function supportsRefraction(): boolean {
  if (refractionSupport !== undefined) return refractionSupport;
  const ua = navigator.userAgent;
  const webkitOnly = /Safari/.test(ua) && !/Chrome|Chromium|Edg/.test(ua);
  refractionSupport =
    !webkitOnly &&
    !/Firefox/.test(ua) &&
    CSS.supports('backdrop-filter', 'url(#a)');
  return refractionSupport;
}

function displacementMap(width: number, height: number, radius: number) {
  const edge = Math.min(width, height) * 0.06;
  const svg = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="r" x1="100%" y1="0%" x2="0%" y2="0%"><stop offset="0%" stop-color="#0000"/><stop offset="100%" stop-color="red"/></linearGradient>
<linearGradient id="b" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#0000"/><stop offset="100%" stop-color="blue"/></linearGradient>
</defs>
<rect width="${width}" height="${height}" fill="black"/>
<rect width="${width}" height="${height}" rx="${radius}" fill="url(#r)"/>
<rect width="${width}" height="${height}" rx="${radius}" fill="url(#b)" style="mix-blend-mode:difference"/>
<rect x="${edge}" y="${edge}" width="${width - edge * 2}" height="${height - edge * 2}" rx="${radius}" fill="hsl(0 0% 50% / 0.94)" style="filter:blur(10px)"/>
</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function Glass<T extends ElementType = 'div'>({
  as,
  variant = 'regular',
  radius = 20,
  refract = true,
  className,
  style,
  children,
  ref,
  ...props
}: GlassProps<T>) {
  // Typed as a div for JSX; the caller's `as` element receives the same props.
  const Component = (as ?? 'div') as 'div';
  const filterId = `glass-${useId().replace(/[^a-zA-Z0-9-]/g, '')}`;
  const element = useRef<HTMLElement>(null);
  // Composite components (e.g. a popover trigger) pass their own ref.
  const setRef = useCallback(
    (node: HTMLElement | null) => {
      element.current = node;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    },
    [ref],
  );
  const image = useRef<SVGFEImageElement>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (!refract || !supportsRefraction() || !element.current) return;
    const target = element.current;
    const update = () => {
      const { width, height } = target.getBoundingClientRect();
      if (width > 0 && height > 0)
        image.current?.setAttribute(
          'href',
          displacementMap(width, height, radius),
        );
    };
    update();
    setActive(true);
    const observer = new ResizeObserver(update);
    observer.observe(target);
    return () => observer.disconnect();
  }, [refract, radius]);

  const scale = DISTORTION[variant];
  return (
    <Component
      ref={setRef}
      className={cn(
        'glass',
        variant === 'thick' && 'glass-thick',
        variant === 'tint' && 'glass-tint',
        className,
      )}
      style={{
        borderRadius: radius,
        ...(active && {
          backdropFilter: `blur(${BLUR_PX[variant]}px) url(#${filterId}) saturate(1.7)`,
        }),
        ...style,
      }}
      {...(props as ComponentPropsWithoutRef<'div'>)}
    >
      {refract && (
        <svg aria-hidden className="pointer-events-none absolute size-0">
          <filter
            id={filterId}
            colorInterpolationFilters="sRGB"
            x="0%"
            y="0%"
            width="100%"
            height="100%"
          >
            <feImage
              ref={image}
              x="0"
              y="0"
              width="100%"
              height="100%"
              preserveAspectRatio="none"
              result="map"
            />
            {(['R', 'G', 'B'] as const).map((channel, i) => (
              <feDisplacementMap
                key={channel}
                in="SourceGraphic"
                in2="map"
                scale={scale + i * 5}
                xChannelSelector="R"
                yChannelSelector="G"
                result={`d${channel}`}
              />
            ))}
            <feColorMatrix
              in="dR"
              type="matrix"
              values="1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0"
              result="r"
            />
            <feColorMatrix
              in="dG"
              type="matrix"
              values="0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 1 0"
              result="g"
            />
            <feColorMatrix
              in="dB"
              type="matrix"
              values="0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 1 0"
              result="b"
            />
            <feBlend in="r" in2="g" mode="screen" result="rg" />
            <feBlend in="rg" in2="b" mode="screen" />
          </filter>
        </svg>
      )}
      {children}
    </Component>
  );
}
