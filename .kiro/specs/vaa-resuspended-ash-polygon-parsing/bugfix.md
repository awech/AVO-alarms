# Bugfix Requirements Document

## Introduction

Volcanic Ash Advisory (VAA) processing fails to parse polygon coordinates and generate a figure for advisories whose cloud fields use the richer real-world format seen in production. The original spec was built on a small set of OBS examples in which each cloud field carries a single level bound-pair followed by one coordinate ring. Two classes of failure have since surfaced:

- **Flight-level prefix (original scope).** A cloud level is expressed as **two flight levels separated by `/`**, giving a lower and an upper altitude bound for the ash cloud (e.g. `SFC/FL060`, `FL200/FL300`, `SFC/060`, `060/090`). Each bound can independently be `FLxxx` (altitude = `xxx * 100` ft), a bare `xxx` (same meaning), or `SFC` (0 ft). The original implementation assumed the `FL` prefix was always present, dropping coordinates or corrupting the parse when it was missing.

- **Forecast / multi-ring format (new scope).** A NEW real-world failure was found that the single-polygon spec does not cover. The production command `run-alarm --test -t 202609010000 VAA` crashed with `ValueError: could not convert string to float: '-FC/060'` inside `text_to_latlon`, called from `process_polygons(vaa, "FCST VA CLD +6HR")`. The forecast cloud fields have a richer format than the OBS examples the spec was built on:

  1. **Leading `DD/HHMM` time token.** Forecast fields begin with a `DD/HHMM` UTC time token, e.g. `01/0858Z`, BEFORE the level. Because this token is itself `digits/digits`, the non-greedy level regex `.*?(?:FL\d+|SFC|\d+)/(?:FL\d+|SFC|\d+)` matches the **time** token (`01/0858`) instead of the real level (`FL100/FL340`). The real level is never stripped, and level text (`SFC/060`, `FLxxx`, ...) is fed into `text_to_latlon` -> `ValueError: could not convert string to float: '-FC/060'`. (OBS fields may have NO time token, or a full `YYYYMMDD/HHMMZ`.)

  2. **Multiple sub-polygons per field.** A single cloud field can contain MULTIPLE sub-polygons, each with its OWN level bounds and its OWN coordinate ring, separated by newlines. The current code treats the whole field as a single ring, so second and later rings are either dropped or merged into one corrupted ring.

  3. **Trailing motion tokens.** `MOV <DIR> <N>KT` tokens (e.g. `MOV ESE 70KT`, `MOV SE 50KT`) appear after the last coordinate of a ring and must NOT be parsed as coordinates.

  4. **Per-sub-polygon `NO VA EXP`.** A sub-polygon can be `NO VA EXP` (e.g. `FL100/FL280 NO VA EXP`) even when a sibling sub-polygon in the same field has real coordinates. That sub-polygon yields no ring but must not crash or drop the sibling.

  5. **Newline-wrapped coordinates.** Coordinates can be wrapped across newlines (e.g. `N4941 W16417` split as `N4941`\n`W16417`); newline normalization to spaces already handles this and must be preserved.

To support multiple rings per field, the `process_polygons` return contract CHANGES from a single `(lons, lats, flight_level_txt)` tuple to a **LIST of per-sub-polygon groups**: `[(lons, lats, level_txt), ...]`, one entry per parsed ring. Empty field / `VA NOT IDENTIFIABLE` / `NO VA EXP` / missing / non-string -> return an EMPTY LIST `[]`. `make_map` (in `src/volc_alarms/alarms/VAA/figure.py`) must iterate the list and plot each sub-polygon ring as its own separate line, keeping a single legend entry per field, and the figure title must show all distinct OBS levels comma-separated.

A representative triggering product remains the MT KATMAI OBS advisory (`SFC/060 ...`), plus the real forecast field that crashed production. A representative real OBS field with two rings is:

```
FL100/FL340 N4941 W16417 - ... - N4941 W16417 MOV ESE 70KT
FL100/FL280 N5723 E17430 - ... - N5723 E17430 MOV SE 50KT
```

and a real forecast field is:

```
01/0858Z FL100/FL340 N4941 W16417 - ... - N4941 W16417 MOV ESE 70KT
FL100/FL280 NO VA EXP
```

## Bug Analysis

### Current Behavior (Defect)

When a forecast cloud field carries a leading `DD/HHMM` time token, or when a field carries more than one sub-polygon, motion tokens, or a per-sub-polygon `NO VA EXP`, coordinate parsing and level derivation break. When a level omits the `FL` prefix (original scope) parsing also breaks.

1.1 WHEN a cloud field contains valid polygon coordinates but neither of the two `/`-separated bounds carries an `FL` prefix (e.g. `SFC/060`, `060/090`) THEN the system skips or mis-handles coordinate parsing and returns empty results from `process_polygons()`
1.2 WHEN a cloud field's level has an `FL` prefix on one bound but not the other (e.g. `060/FL200`) THEN the level token is not correctly stripped and is mis-parsed as a coordinate pair, corrupting the parsed coordinates
1.3 WHEN a bound is expressed as a bare number without the `FL` prefix (e.g. `060`) THEN the system maps its altitude to `np.nan` and produces no level text even though the level is valid
1.4 WHEN a forecast cloud field begins with a `DD/HHMM` UTC time token (e.g. `01/0858Z`) before the level THEN the non-greedy level regex matches the `digits/digits` time token instead of the real level, the real level (e.g. `FL100/FL340`) is not stripped, and level text is fed into `text_to_latlon()` -> `ValueError: could not convert string to float: '-FC/060'` (the production crash from `run-alarm --test -t 202609010000 VAA`)
1.5 WHEN a single cloud field contains multiple sub-polygons, each with its own level bounds and its own coordinate ring separated by newlines THEN the system treats the whole field as one ring, so the second and later rings are dropped or merged into a single corrupted ring
1.6 WHEN a coordinate ring ends with a motion token `MOV <DIR> <N>KT` (e.g. `MOV ESE 70KT`) THEN the system attempts to parse the motion token as a coordinate pair, corrupting or crashing the parse
1.7 WHEN a sub-polygon within a field is `NO VA EXP` (e.g. `FL100/FL280 NO VA EXP`) while a sibling sub-polygon in the same field has real coordinates THEN the system may crash or drop the sibling ring instead of skipping only the `NO VA EXP` sub-polygon

### Expected Behavior (Correct)

2.1 WHEN a cloud field contains valid polygon coordinates THEN the system SHALL parse the coordinates and return them from `process_polygons()`, regardless of whether either of the two `/`-separated bounds carries an `FL` prefix
2.2 WHEN a cloud field's level is expressed as any combination of the two bound forms (`FLxxx`, bare `xxx`, or `SFC`) THEN the system SHALL recognize the full level token and strip it from the coordinate text, so the level token is never mis-parsed as a coordinate pair
2.3 WHEN computing altitude for each bound THEN the system SHALL map `SFC` to 0 ft, `FLxxx` to `xxx * 100` ft, and a bare `xxx` to `xxx * 100` ft (else NaN, suppressing that ring's level text while still returning its coordinates)
2.4 WHEN both bounds of a level resolve to valid altitudes THEN the system SHALL produce the corresponding level text (e.g. `SFC/060` yields `0 - 6,000 ft`, `FL100/FL340` yields `10,000 - 34,000 ft`)
2.5 WHEN a forecast cloud field begins with a `DD/HHMM` time token (e.g. `01/0858Z`) before the level THEN the system SHALL recognize the level ONLY where a `(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)` bound-pair is immediately followed by whitespace and a coordinate token (`[NS]\d`), skip the time token, and strip the real level so it is never fed into `text_to_latlon()`
2.6 WHEN a single cloud field contains multiple sub-polygons, each with its own level bounds and its own coordinate ring THEN the system SHALL split the field into sub-polygon segments at each level-token boundary and return one `(lons, lats, level_txt)` group per parsed ring
2.7 WHEN a coordinate ring ends with a motion token `MOV <DIR> <N>KT` THEN the system SHALL ignore the trailing motion token and NOT parse it as a coordinate pair
2.8 WHEN a sub-polygon within a field is `NO VA EXP` while a sibling has real coordinates THEN the system SHALL skip only the `NO VA EXP` sub-polygon, yield no ring for it, and still return the sibling ring(s) without crashing
2.9 WHEN `process_polygons()` is called THEN it SHALL return a LIST of per-sub-polygon groups `[(lons, lats, level_txt), ...]` (one entry per parsed ring), returning an EMPTY LIST `[]` for empty / `VA NOT IDENTIFIABLE` / whole-field `NO VA EXP` / missing / non-string fields
2.10 WHEN `make_map()` renders an advisory THEN it SHALL iterate the list of groups per field and plot EACH sub-polygon ring as its OWN separate line (no spurious connecting line between distinct rings), applying that field's style to each ring and keeping a single legend entry per field (label only the first ring; suppress duplicate legend labels for subsequent rings, e.g. via `label='_nolegend_'`)
2.11 WHEN `make_map()` builds the figure title THEN it SHALL show ALL DISTINCT OBS levels, comma-separated (e.g. `10,000 - 34,000 ft, 10,000 - 28,000 ft`), preserving the otherwise-unchanged title format `{volcano_name} VAA\n{levels}\n{vaa_time}`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a cloud field carries a single sub-polygon with an `FL`-prefixed level (e.g. `SFC/FL060`, `FL200/FL300`) THEN the system SHALL CONTINUE TO parse the same coordinates and derive the same level text as before, modulo the new list wrapping (a single-element list with one `(lons, lats, level_txt)` group)
3.2 WHEN a cloud field contains `VA NOT IDENTIFIABLE` THEN the system SHALL CONTINUE TO produce no polygons (an empty list under the new contract)
3.3 WHEN a cloud field is absent from the advisory or is not a string THEN the system SHALL CONTINUE TO produce no polygons (an empty list) without error
3.4 WHEN a whole forecast cloud field indicates `NO VA EXP` THEN the system SHALL CONTINUE TO produce no polygons for that field (an empty list)
3.5 WHEN an advisory genuinely contains no valid coordinates in any cloud field THEN `make_map()` SHALL CONTINUE TO log `No polygons to plot. Not generating figure.` and skip figure generation
3.6 WHEN converting individual coordinate pairs via `text_to_latlon()` THEN the system SHALL CONTINUE TO produce the same latitude/longitude values as before (`text_to_latlon` is unchanged by this fix)
3.7 WHEN coordinates are wrapped across newlines within a ring THEN the system SHALL CONTINUE TO join them correctly via the existing newline-to-space normalization

## Bug Condition and Properties

### Bug Condition

```pascal
FUNCTION isBugCondition(vaa, field)
  INPUT: vaa (parsed advisory), field (cloud field name, e.g. "OBS VA CLD")
  OUTPUT: boolean

  // The field exists, is a string, is not an "unidentifiable"/"whole-field no VA"
  // case, and contains at least one valid sub-polygon ring, AND it exhibits at
  // least one of the real-format features the current code mishandles:
  //  - a bound lacking an "FL" prefix (SFC or bare number), OR
  //  - a leading DD/HHMM time token before the level, OR
  //  - more than one sub-polygon (multiple level-token boundaries), OR
  //  - a trailing MOV <DIR> <N>KT motion token, OR
  //  - a per-sub-polygon NO VA EXP alongside a sibling ring.
  RETURN field IN vaa
     AND isString(vaa[field])
     AND NOT contains(vaa[field], "VA NOT IDENTIFIABLE")
     AND NOT isWholeFieldNoVaExp(vaa[field])
     AND hasAtLeastOneValidRing(vaa[field])
     AND ( levelHasBoundWithoutFLPrefix(vaa[field])
        OR hasLeadingTimeToken(vaa[field])
        OR hasMultipleSubPolygons(vaa[field])
        OR hasMotionToken(vaa[field])
        OR hasPerSubPolygonNoVaExp(vaa[field]) )
END FUNCTION
```

Where the level token is recognized ONLY when a `(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)` bound-pair is immediately followed by whitespace and a coordinate token (`[NS]\d`), which distinguishes the real level from the leading `DD/HHMM` time token (which is followed by the level, not a coordinate; the stamp appears as `DD/HHMMZ` or `DD/HHMM` with no trailing `Z`, so the `Z` is NOT relied on) and from digit runs inside coordinates.

### Fix Checking Property

```pascal
// Property: Fix Checking - real-format cloud fields parse every sub-polygon
// into its own ring + level, skipping time tokens and MOV motion tokens.
FOR ALL X WHERE isBugCondition(X) DO
  groups <- process_polygons'(X.vaa, X.field)   // list of (lons, lats, level_txt)
  ASSERT length(groups) = numberOfValidRings(X.field)
  FOR EACH (lons, lats, level_txt) IN groups DO
    ASSERT length(lons) > 0 AND length(lats) > 0
    ASSERT length(lons) = length(lats)
    ASSERT lons, lats EQUAL the coordinates of that ring
           (level token, leading DD/HHMM time token, and trailing
            MOV ... KT motion tokens are NOT included as coordinate pairs)
    ASSERT level_txt is computed per bound via SFC -> 0, FLxxx -> xxx*100,
           bare xxx -> xxx*100 (else "" for that ring when a bound is unparseable)
  END FOR
END FOR
```

Concrete counterexamples (currently fail, must pass after fix):

- The production forecast field `01/0858Z FL100/FL340 N4941 W16417 - ... MOV ESE 70KT` followed by `FL100/FL280 NO VA EXP` must NOT raise `ValueError: could not convert string to float: '-FC/060'`; it must yield one ring for `FL100/FL340` (level text `10,000 - 34,000 ft`) and skip the `NO VA EXP` sub-polygon.
- The two-ring OBS field `FL100/FL340 ... MOV ESE 70KT` / `FL100/FL280 ... MOV SE 50KT` must yield two rings with level text `10,000 - 34,000 ft` and `10,000 - 28,000 ft`.
- The MT KATMAI `SFC/060 ...` field must yield one ring with 7 coordinate pairs and level text `0 - 6,000 ft`.

### Preservation Property

```pascal
// Property: Preservation Checking - single-sub-polygon FL fields, non-coordinate
// cases, and per-pair conversion are unchanged (modulo the new list wrapping).
FOR ALL X WHERE NOT isBugCondition(X) DO
  groups <- process_polygons'(X.vaa, X.field)
  IF X is a single-ring FL-prefixed field THEN
    ASSERT groups = [ originalTuple(X) ]   // one group equal to the old tuple
  ELSE  // VA NOT IDENTIFIABLE / whole-field NO VA EXP / missing / non-string
    ASSERT groups = []
  END IF
END FOR
```

Where `process_polygons` is the original (unfixed) function returning a single tuple and `process_polygons'` is the fixed function returning a list. Preservation means the coordinates and level text for each unchanged case match the original, wrapped as a single-element list for a valid single ring and `[]` for the non-coordinate cases. `text_to_latlon()` remains byte-for-byte unchanged.
