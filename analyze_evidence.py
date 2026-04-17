import json
from collections import Counter, defaultdict

with open('logs/phase2_evidence.json') as f:
    ev = json.load(f)

# REVERSE cases
reverse = [e for e in ev if e.get('direction_hint') == 'REVERSE']
print(f'REVERSE cases: {len(reverse)}')
for e in reverse[:12]:
    print(f"  arrow={e['arrow_id']} lps={e['pipe_segment_id']} cos={e['cosine_alignment']} "
          f"pixel={e.get('pixel_direction')} dx={e['dx']} dy={e['dy']}")

print()
print('pixel_direction breakdown:', Counter(e.get('pixel_direction') for e in ev))
print('direction_hint breakdown:', Counter(e.get('direction_hint') for e in ev))

print()
print('=== Multi-bound arrows ===')
arrow_bindings = defaultdict(list)
for e in ev:
    arrow_bindings[e['arrow_id']].append(e)

for aid, bindings in sorted(arrow_bindings.items()):
    if len(bindings) > 1:
        dirs = [b['direction_hint'] for b in bindings]
        lps  = [b['pipe_segment_id'] for b in bindings]
        consistent = len(set(dirs)) == 1
        flag = '✓' if consistent else '✗ CONFLICT'
        print(f"  {aid}: {dirs} {flag}")
        for b in bindings:
            print(f"    → {b['pipe_segment_id']} | {b['direction_hint']} | cos={b['cosine_alignment']} | pixel={b.get('pixel_direction')}")

print()
print('=== REVERSE arrow dual-binding check ===')
for aid, bindings in sorted(arrow_bindings.items()):
    if any(b['direction_hint'] == 'REVERSE' for b in bindings):
        dirs = [b['direction_hint'] for b in bindings]
        lps  = [b['pipe_segment_id'] for b in bindings]
        print(f"  {aid}: {list(zip(lps, dirs))}")
