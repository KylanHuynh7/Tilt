// Primary brand color per franchise (current 32). Sourced from each team's
// published identity guidelines and tuned for a light background. Teams whose
// official primary is gold or a pale color (NSH gold, SEA ice blue, UTA glacier
// blue) use a slightly darker secondary so the line is readable on white.
export const TEAM_COLORS: Record<string, string> = {
  ANA: "#F47A38", // Anaheim orange
  BOS: "#111111", // Bruins black (gold washes out on white)
  BUF: "#003087", // Buffalo royal blue
  CAR: "#CC0000", // Hurricanes red
  CBJ: "#002654", // Columbus navy
  CGY: "#C8102E", // Calgary red
  CHI: "#CF0A2C", // Blackhawks red
  COL: "#6F263D", // Avalanche burgundy
  DAL: "#006847", // Stars victory green
  DET: "#CE1126", // Red Wings red
  EDM: "#FF4C00", // Oilers orange
  FLA: "#041E42", // Panthers navy
  LAK: "#111111", // Kings black (silver too low contrast on white)
  MIN: "#154734", // Wild forest green
  MTL: "#AF1E2D", // Canadiens red
  NJD: "#CE1126", // Devils red
  NSH: "#B89200", // Predators gold (darkened so it reads on white)
  NYI: "#00539B", // Islanders blue
  NYR: "#0038A8", // Rangers blue
  OTT: "#C8102E", // Senators red
  PHI: "#F74902", // Flyers orange
  PIT: "#111111", // Penguins black (gold washes out on white)
  SEA: "#001628", // Kraken deep sea blue (ice blue too pale on white)
  SJS: "#006D75", // Sharks teal
  STL: "#002F87", // Blues blue
  TBL: "#002868", // Lightning blue
  TOR: "#00205B", // Maple Leafs blue
  UTA: "#1A6FB0", // Utah Mammoth (glacier blue darkened for readability)
  VAN: "#00205B", // Canucks blue
  VGK: "#8E7438", // Golden Knights gold (darkened so it reads on white)
  WPG: "#041E42", // Jets navy
  WSH: "#C8102E", // Capitals red
};

export function colorFor(team: string): string {
  return TEAM_COLORS[team] ?? "#888888";
}
