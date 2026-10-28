import React from 'react'
import { AbsoluteFill, Composition, registerRoot } from 'remotion'
import type { CalculateMetadataFunction } from 'remotion'
import {
  CaptionTrack,
  EditorialEmphasis,
  KaraokeFill,
  KineticSlam,
  NeonGlow,
  PillKaraoke,
  WeightShift,
  captionsFromWords,
  useCaptionPages,
  type CaptionTheme,
  type WordTiming
} from 'remotion-captions-kit'

export type CaptionPreset = 'karaoke' | 'kinetic' | 'pill' | 'weight' | 'neon' | 'editorial'

export type CaptionInput = {
  words: WordTiming[]
  preset: CaptionPreset
  theme: CaptionTheme
  uppercase: boolean
  duration: number
  maxCharsPerPage: number
  minWordsPerPage: number
  maxDurationMs: number
}

const PRESETS = {
  karaoke: KaraokeFill,
  kinetic: KineticSlam,
  pill: PillKaraoke,
  weight: WeightShift,
  neon: NeonGlow,
  editorial: EditorialEmphasis
}

const ReelCaptions: React.FC<CaptionInput> = ({ words, preset, theme, uppercase, maxCharsPerPage, minWordsPerPage, maxDurationMs }) => {
  const prepared = words.map((word) => ({
    ...word,
    word: uppercase ? word.word.toLocaleUpperCase('ru-RU') : word.word
  }))
  const { captions } = captionsFromWords({ words: prepared, timeUnit: 'seconds' })
  const { pages } = useCaptionPages({
    captions,
    maxDurationMs: maxDurationMs || 800,
    maxCharsPerPage: maxCharsPerPage || 18,
    minWordsPerPage: minWordsPerPage || 1,
    silenceGapMs: 280,
    minDurationMs: 160
  })
  const Preset = PRESETS[preset] ?? KineticSlam
  return (
    <AbsoluteFill style={{ backgroundColor: 'transparent' }}>
      <CaptionTrack pages={pages}>{(page) => <Preset page={page} theme={theme} />}</CaptionTrack>
    </AbsoluteFill>
  )
}

const calculateMetadata: CalculateMetadataFunction<CaptionInput> = ({ props }) => {
  const last = props.words.reduce((max, word) => Math.max(max, word.end || 0), 0)
  const seconds = Math.max(props.duration || 0, last, 0.2)
  return {
    durationInFrames: Math.max(1, Math.ceil(seconds * 30)),
    fps: 30,
    width: 1080,
    height: 1920,
    props
  }
}

const defaultProps: CaptionInput = {
  words: [],
  preset: 'kinetic',
  uppercase: true,
  duration: 1,
  maxCharsPerPage: 18,
  minWordsPerPage: 1,
  maxDurationMs: 800,
  theme: {
    position: 'bottom',
    edgeOffset: 0.3,
    fontFamily: 'Arial Black',
    fontSize: 82,
    textColor: '#FFFFFF',
    activeColor: '#FFE14A',
    pillColor: '#141414',
    maxWidth: 0.92
  }
}

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ReelCaptions"
      component={ReelCaptions}
      durationInFrames={30}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={defaultProps}
      calculateMetadata={calculateMetadata}
    />
  )
}

registerRoot(RemotionRoot)
