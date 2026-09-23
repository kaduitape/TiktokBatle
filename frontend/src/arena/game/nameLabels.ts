import Phaser from "phaser";

/** Keeping every viewer's name readable when their avatars crowd together.
 *
 * Names are centred under their own avatar, which is fine until two avatars
 * end up side by side: the labels then overlap into an unreadable smudge, and
 * a live with a hundred people is mostly side-by-side avatars.
 *
 * Simply pushing the names further down would not help -- the collision is
 * horizontal. So a label that would sit on top of one already placed drops to
 * the next line instead. Everybody keeps a name; the ones that would have
 * collided are just stacked.
 */

export interface NameLabelTarget {
  label: Phaser.GameObjects.Text;
  /** Where the name wants to be: centred under its avatar. */
  x: number;
  y: number;
  /** Optional anchor above the avatar. When given, bumped names alternate
   * between above and below instead of marching downwards -- which halves how
   * far the stack reaches and keeps it off whatever sits under the avatars.
   * In the tank war that is the event feed. */
  yAbove?: number;
}

/** Gap kept between two names on the same line. */
const HORIZONTAL_GAP = 8;

/** How far down a bumped name drops. */
const LINE_HEIGHT = 20;

/** Past this, the stack would reach the next avatar down, and a name that far
 * from its owner is worse than no name -- those are hidden instead. */
const MAX_ROWS = 3;

/** Row 0 sits under the avatar. With an anchor above, the next rows
 * alternate up and down; without one they march downwards. */
function rowY(target: NameLabelTarget, row: number): number {
  if (row === 0 || target.yAbove === undefined) {
    return target.y + row * LINE_HEIGHT;
  }
  const step = Math.ceil(row / 2);
  return row % 2 === 1
    ? target.yAbove - (step - 1) * LINE_HEIGHT
    : target.y + step * LINE_HEIGHT;
}

export function layoutNameLabels(targets: NameLabelTarget[]): void {
  // Left to right, so "the one already placed" is always the neighbour on the
  // left and a single pass is enough.
  const ordered = [...targets].sort((a, b) => a.x - b.x);

  // The right edge occupied so far on each line.
  const rowEnds: number[] = [];

  for (const target of ordered) {
    const half = target.label.width / 2;
    const left = target.x - half;

    let row = 0;
    while (row < MAX_ROWS && rowEnds[row] !== undefined && left < rowEnds[row] + HORIZONTAL_GAP) {
      row += 1;
    }

    if (row >= MAX_ROWS) {
      // Too crowded to place honestly. Hiding beats pointing at the wrong
      // person.
      target.label.setVisible(false);
      continue;
    }

    target.label.setVisible(true);
    target.label.setPosition(target.x, rowY(target, row));
    rowEnds[row] = target.x + half;
  }
}
