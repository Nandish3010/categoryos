import impact from './data/impact.json';

/**
 * Set this to your own measured numbers to switch the captions from "research estimate" to "measured":
 *   export const MEASURED_BASELINE = { hoursPerVendor: 14, minutesWithCos: 25 };
 * While it is null, every baseline figure is labelled as a research estimate.
 */
export type Baseline = { hoursPerVendor: number; minutesWithCos: number } | null;
export const MEASURED_BASELINE = null as Baseline;

export const RESEARCH_ESTIMATE_HOURS = 18;
export const baselineHours = MEASURED_BASELINE ? MEASURED_BASELINE.hoursPerVendor : RESEARCH_ESTIMATE_HOURS;
export const baselineTag = MEASURED_BASELINE ? 'measured' : 'research estimate';
export const chaosCaption = `≈${baselineHours} hours. One vendor.`;

export const URL = 'https://categoryos.vercel.app';
export const MODELS = ['muse-spark-1.3', 'sam-3.1', 'muse-image-1.0', 'muse-voice-transcribe-1.0', 'Muse Spark Open on Baseten'];

/** Figures read from the live GET /api/impact (captured by `make video`); see capture/capture.mjs impact flow. */
export const IMPACT = impact as Record<string, unknown>;

/**
 * The people shown in the "Meet the team" scene (a2-team). Edit this list to change the cast:
 *   { name, role, photo }  where `photo` is an optional file under video/assets/team/ (e.g. 'nandish.jpg'), served via staticFile('team/<file>').
 * With `photo: null` the card shows an initials avatar. One member gets a wide card, several share the row.
 */
export type TeamMember = { name: string; role: string; photo: string | null };
export const TEAM: TeamMember[] = [{ name: 'Nandish', role: 'Builder: product, agents and code', photo: null as string | null }];
/** The line under the team card. */
export const TEAM_BUILT_FOR = ['Built for the Meta hackathon', 'Muse Spark', 'SAM 3.1', 'Muse Image', 'Muse Voice'];
