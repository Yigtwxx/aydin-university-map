'use client';

import type { CSSProperties } from 'react';

import type { SkyPhase } from './hooks';
import { Precipitation } from './Precipitation';
import {
  precipitationIntensity,
  rainSlant,
  SKY_GRADIENTS,
  skyArtOf,
  skyKindOf,
} from './skyTheme';
import { useSkyTexture } from './skyTextures';
import type { Condition } from './weather';

const texture = (url: string): CSSProperties => ({
  backgroundImage: `url(${url})`,
});

/**
 * The weather sheet's backdrop: the sky for the weather and the hour the map
 * shows, previews included. Cloud and fog are drifting noise textures, rain
 * and snow fall on a canvas; all of it is decorative and holds still under
 * reduced motion.
 */
export function WeatherSky({
  condition,
  phase,
  wind,
}: {
  condition?: Condition;
  phase: SkyPhase;
  /** The live wind, which slants the rain. */
  wind?: { speedKmh: number; fromDeg: number };
}) {
  const kind = skyKindOf(condition);
  const [top, bottom] = SKY_GRADIENTS[kind][phase];
  const art = skyArtOf(kind, phase);
  const clouds = useSkyTexture(art.clouds);
  const fog = useSkyTexture(art.fog ? 'fog' : undefined);
  return (
    <div
      aria-hidden
      data-sky={kind}
      data-phase={phase}
      className="sky pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-[inherit]"
      style={{ '--sky-top': top, '--sky-bottom': bottom } as CSSProperties}
    >
      {/* Keyed so a new sky's art fades in rather than jumping. */}
      <div key={`${kind}-${phase}`} className="sky-art">
        {art.stars && (
          <>
            <div className="sky-stars sky-stars-a" />
            <div className="sky-stars sky-stars-b" />
          </>
        )}
        {art.glow && <div className={`sky-glow sky-glow-${art.glow}`} />}
        {(art.glow === 'sun' || art.glow === 'sunset') && (
          <div className="sky-sun-rays" />
        )}
        {/* Cloud drifts in front of the sunlight. */}
        {clouds && (
          <>
            <div className="sky-layer sky-cloud-far" style={texture(clouds)} />
            <div className="sky-layer sky-cloud-near" style={texture(clouds)} />
          </>
        )}
        {fog && (
          <>
            <div className="sky-layer sky-fog-far" style={texture(fog)} />
            <div className="sky-layer sky-fog-near" style={texture(fog)} />
          </>
        )}
        {art.precipitation && (
          <Precipitation
            kind={art.precipitation}
            intensity={precipitationIntensity(condition)}
            wind={art.precipitation === 'rain' ? rainSlant(wind) : 0.08}
          />
        )}
      </div>
    </div>
  );
}
