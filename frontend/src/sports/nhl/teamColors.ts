// Primary brand color per franchise (current 32). Sourced from each team's
// published identity guidelines. Tuned for a DARK background (current
// broadcast-graphics theme). Teams whose official primary is a deep navy or
// black (BOS, PIT, LAK with black primaries) use their secondary gold/silver
// since pure black would vanish on the dark UI.
export const TEAM_COLORS: Record<string, string> = {
  ANA: "#F47A38", // Anaheim orange
  BOS: "#FFB81C", // Bruins gold (black would vanish on dark)
  BUF: "#003087", // Buffalo royal blue
  CAR: "#CC0000", // Hurricanes red
  CBJ: "#002654", // Columbus navy
  CGY: "#C8102E", // Calgary red
  CHI: "#CF0A2C", // Blackhawks red
  COL: "#8B2942", // Avalanche burgundy (lightened slightly for dark bg)
  DAL: "#0E8259", // Stars victory green (lightened for dark bg)
  DET: "#CE1126", // Red Wings red
  EDM: "#FF4C00", // Oilers orange
  FLA: "#0B3D7A", // Panthers navy (lightened for dark bg)
  LAK: "#A2AAAD", // Kings silver (black would vanish on dark)
  MIN: "#2A7A57", // Wild green (lightened for dark bg)
  MTL: "#AF1E2D", // Canadiens red
  NJD: "#CE1126", // Devils red
  NSH: "#FFB81C", // Predators gold
  NYI: "#00539B", // Islanders blue
  NYR: "#0038A8", // Rangers blue
  OTT: "#C8102E", // Senators red
  PHI: "#F74902", // Flyers orange
  PIT: "#FCB514", // Penguins Vegas gold (black would vanish on dark)
  SEA: "#99D9D9", // Kraken ice blue
  SJS: "#006D75", // Sharks teal
  STL: "#1A47B0", // Blues blue (lightened for dark bg)
  TBL: "#0F4DB5", // Lightning blue (lightened for dark bg)
  TOR: "#0033A0", // Maple Leafs blue (lightened for dark bg)
  UTA: "#71AFE5", // Utah Mammoth glacier blue
  VAN: "#0033A0", // Canucks blue (lightened for dark bg)
  VGK: "#B4975A", // Golden Knights gold
  WPG: "#0B3D7A", // Jets navy (lightened for dark bg)
  WSH: "#C8102E", // Capitals red
};

export function colorFor(team: string): string {
  return TEAM_COLORS[team] ?? "#888888";
}
