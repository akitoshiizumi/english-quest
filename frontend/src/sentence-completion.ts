type Range = {start: number; end: number} | null;

/** Credit complete, actually played sentences; seeks start a new traversal. */
export class SentenceCompletionTracker {
  ranges: Range[] = [];
  private previous: number | null = null;
  private covered = new Map<number,number>();
  private completed = new Set<number>();

  private readonly onComplete: (index: number) => void;
  constructor(onComplete: (index: number) => void) {this.onComplete=onComplete;}

  reset(): void { this.previous=null; this.covered.clear(); this.completed.clear(); }
  pause(): void { this.previous=null; }
  resume(position: number): void { this.previous=position; }

  advance(position: number): void {
    const previous=this.previous;
    this.previous=position;
    if(previous===null)return;
    const delta=position-previous;
    if(delta<0||delta>1.5){this.reset();this.previous=position;return;}
    if(delta===0)return;
    this.ranges.forEach((range,index)=>{
      if(!range||this.completed.has(index))return;
      const overlap=Math.max(0,Math.min(position,range.end)-Math.max(previous,range.start));
      const covered=(this.covered.get(index)||0)+overlap;
      this.covered.set(index,covered);
      if(position>=range.end-0.025&&covered>=(range.end-range.start)*0.9){
        this.completed.add(index);
        this.onComplete(index);
      }
    });
  }
}
