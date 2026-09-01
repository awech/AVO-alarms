# Bugfix Requirements Document

## Introduction

Volcanic Ash Advisory (VAA) processing fails to parse polygon coordinates and generate a figure for advisories whose cloud level does not use the `FL` flight-level prefix on both bounds, even when the advisory contains valid polygon coordinates. Affected runs log `No polygons to plot. Not generating figure.` and produce no map, silently dropping a legitimate detection.

A VAA cloud level is expressed as **two flight levels separated by `/`**, giving a lower and an upper altitude bound for the ash cloud (e.g. `SFC/FL060`, `FL200/FL300`, `SFC/060`, `060/090`). Each of the two bounds can independently take any of these forms:

- `FLxxx` — flight level with the `FL` prefix; altitude = `xxx * 100` ft
- `xxx` — a bare number with no `FL` prefix; same meaning, altitude = `xxx * 100` ft
- `SFC` — surface; altitude = 0 ft

The defect is that `process_polygons()` (in `src/volc_alarms/alarms/VAA/detection.py`) assumes the `FL` prefix is always present. This is a **general** parsing defect, not one specific to surface-level or resuspended-ash advisories: any advisory where the `FL` prefix is missing on one or both bounds is mishandled. Three distinct failures flow from the same wrong assumption:

1. **Coordinate-parsing gate.** All coordinate parsing is nested inside `if "FL" in obs_text:`. When neither bound carries an `FL` prefix (e.g. `SFC/060`, `060/090`), the substring `FL` is absent, the whole block is skipped, and empty latitude/longitude lists are returned. `make_map()` (in `figure.py`) then sees zero coordinates across all fields and logs `No polygons to plot. Not generating figure.`

2. **Level-token regex.** `lvl_pattern = re.compile(r".*\S+/FL\S+")` requires the token after the `/` to start with `FL`. A level such as `060/FL200` (bare lower bound) or `060/090` (both bare) does not match. When the match fails, `time_and_level` becomes `""`, nothing is stripped from the coordinate text, and the level token is fed into `text_to_latlon()` as if it were the first coordinate pair, corrupting the coordinate parse.

3. **Height mapping.** Inside the level loop, `if fl == "SFC": height = 0`, `elif "FL" in fl: height = xxx * 100`, `else: height = np.nan`. A bare `060` (no `FL` prefix) falls into the `else` branch and becomes `np.nan`, so `np.nan in flight_levels` is true and no `flight_level_txt` is produced even for a perfectly valid level.

A representative triggering product is the MT KATMAI advisory, whose `OBS VA CLD` field is:
`SFC/060 N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - N5741 W15459 - N5818 W15524 - N5825 W15450 STNR`

The coordinates in this product are valid and well-formed; only the `FL`-prefix assumptions are wrong.

## Bug Analysis

### Current Behavior (Defect)

When a VAA cloud level omits the `FL` prefix on one or both of its two `/`-separated bounds, coordinate parsing and/or level derivation is broken.

1.1 WHEN a cloud field contains valid polygon coordinates but neither of the two `/`-separated bounds carries an `FL` prefix (e.g. `SFC/060`, `060/090`) THEN the system skips all coordinate parsing and returns empty latitude and longitude lists from `process_polygons()`
1.2 WHEN a cloud field's level has an `FL` prefix on one bound but not the other (e.g. `060/FL200`) THEN the level-token regex fails to match, the level token is not stripped from the coordinate text, and it is mis-parsed as a coordinate pair, corrupting the parsed coordinates
1.3 WHEN a bound is expressed as a bare number without the `FL` prefix (e.g. `060`) THEN the system maps its altitude to `np.nan`, and no `flight_level_txt` is produced even though the level is valid
1.4 WHEN an advisory that actually contains valid coordinates yields empty coordinate lists for all cloud fields because of 1.1 THEN `make_map()` logs `No polygons to plot. Not generating figure.` and generates no figure

### Expected Behavior (Correct)

2.1 WHEN a cloud field contains valid polygon coordinates THEN the system SHALL parse the coordinates and return the corresponding latitude and longitude lists from `process_polygons()`, regardless of whether either of the two `/`-separated bounds carries an `FL` prefix
2.2 WHEN a cloud field's level is expressed as any combination of the two bound forms (`FLxxx`, bare `xxx`, or `SFC`) THEN the system SHALL recognize the full level token and strip it from the coordinate text, so the level token is never mis-parsed as a coordinate pair
2.3 WHEN computing altitude for each bound THEN the system SHALL map `SFC` to 0 ft, `FLxxx` to `xxx * 100` ft, and a bare `xxx` to `xxx * 100` ft
2.4 WHEN both bounds of a level resolve to valid altitudes THEN the system SHALL produce the corresponding level text (e.g. `SFC/060` yields `0 - 6,000 ft`)
2.5 WHEN an advisory contains at least one cloud field with valid polygon coordinates THEN `make_map()` SHALL generate the figure regardless of the `FL`-prefix combination used in the level

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a cloud level uses `FL` prefixes as before (e.g. `SFC/FL060`, `FL200/FL300`) THEN the system SHALL CONTINUE TO parse the coordinates and derive the level text exactly as before
3.2 WHEN a cloud field contains `VA NOT IDENTIFIABLE` THEN the system SHALL CONTINUE TO return empty coordinate lists and skip that field
3.3 WHEN a cloud field is absent from the advisory or is not a string THEN the system SHALL CONTINUE TO return empty coordinate lists without error
3.4 WHEN a forecast cloud field indicates `NO VA EXP` THEN the system SHALL CONTINUE TO produce no polygons for that field
3.5 WHEN an advisory genuinely contains no valid coordinates in any cloud field THEN the system SHALL CONTINUE TO log `No polygons to plot. Not generating figure.` and skip figure generation
3.6 WHEN converting individual coordinate pairs via `text_to_latlon()` THEN the system SHALL CONTINUE TO produce the same latitude/longitude values as before

## Bug Condition and Properties

### Bug Condition

```pascal
FUNCTION isBugCondition(vaa, field)
  INPUT: vaa (parsed advisory), field (cloud field name, e.g. "OBS VA CLD")
  OUTPUT: boolean

  // The field exists, is a string, is not an "unidentifiable"/"no VA" case,
  // and contains valid polygon coordinates, but at least one of the two
  // "/"-separated level bounds lacks an "FL" prefix (i.e. it is "SFC" or a
  // bare number). This covers the gate, regex, and height-mapping failures.
  RETURN field IN vaa
     AND isString(vaa[field])
     AND NOT contains(vaa[field], "VA NOT IDENTIFIABLE")
     AND hasValidCoordinates(vaa[field])
     AND levelHasBoundWithoutFLPrefix(vaa[field])
END FUNCTION
```

### Fix Checking Property

```pascal
// Property: Fix Checking - levels without an FL prefix on every bound
// still parse coordinates and compute level text correctly.
FOR ALL X WHERE isBugCondition(X) DO
  (lons, lats, level_txt) ← process_polygons'(X.vaa, X.field)
  ASSERT length(lons) > 0 AND length(lats) > 0
  ASSERT length(lons) = length(lats)
  ASSERT lons, lats EQUAL the coordinates parsed from X.field
         (the level token is NOT included as a coordinate pair)
  ASSERT level_txt is computed via SFC -> 0, FLxxx -> xxx*100, bare xxx -> xxx*100
END FOR
```

Concrete counterexample (currently fails, must pass after fix): the MT KATMAI `OBS VA CLD` field
`SFC/060 N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - N5741 W15459 - N5818 W15524 - N5825 W15450 STNR`
must yield 7 coordinate pairs, produce level text `0 - 6,000 ft`, and cause `make_map()` to generate a figure.

### Preservation Property

```pascal
// Property: Preservation Checking - FL-prefixed levels, non-coordinate
// cases, and per-pair conversion are unchanged.
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT process_polygons(X.vaa, X.field) = process_polygons'(X.vaa, X.field)
END FOR
```

Where `process_polygons` is the original (unfixed) function and `process_polygons'` is the fixed function.
