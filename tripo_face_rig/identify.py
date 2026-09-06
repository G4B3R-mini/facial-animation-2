"""Stage -1: work out which object is which, by name.

Every mesh in a Tripo head export arrives with a role in its name -- head,
hair, upper_jaw, tongue, eyebrow_l -- and until now the pipeline ignored all
of it and took the densest mesh as the head.  That is wrong far more often
than it looks: hair is routinely the densest object in the file (18,436 verts
against the head's 6,046 on the first character tested), so the default
silently rigged a wig.  The failure is quiet, too -- measurement succeeds, the
gates pass, and the only symptom is bones behind the skull.

So: match on names, and when the names do not settle it, say so and stop
rather than guessing.  Explicit --obj/--teeth/--tongue-object still win; this
only fills in what the caller left blank.
"""
import re

# Ordered: the first pattern that matches a name wins, so the specific
# entries (eyebrow, eyelash) must precede the general one they contain (eye).
_ROLES = [
    ("hair",         (r"hair", r"^wig", r"fringe", r"bangs", r"braid",
                      r"ponytail")),
    ("eyebrow",      (r"eye_?brow", r"^brow")),
    ("eyelash",      (r"eye_?lash", r"^lash")),
    ("eye",          (r"^eyes?$", r"^eye[_.]", r"eye_?ball", r"cornea",
                      r"iris", r"sclera")),
    ("upper_teeth",  (r"upper_?(jaw|teeth|tooth)", r"teeth_?upper",
                      r"^top_?teeth")),
    ("lower_teeth",  (r"lower_?(jaw|teeth|tooth)", r"teeth_?lower",
                      r"^bottom_?teeth")),
    ("teeth",        (r"teeth", r"^tooth", r"denture")),
    ("tongue",       (r"tongue",)),
    ("gums",         (r"gums?$", r"gingiva")),
    ("mouth_bag",    (r"mouth_?bag", r"oral_?cavity", r"mouth_?interior")),
    ("head",         (r"^head$", r"^face$", r"^head[_.]", r"^face[_.]",
                      r"body", r"skin", r"^avatar", r"^character", r"^mesh$")),
]

# Roles that must never be mistaken for the head, whatever their vertex count.
NOT_HEAD = {"hair", "eyebrow", "eyelash", "eye", "upper_teeth", "lower_teeth",
            "teeth", "tongue", "gums", "mouth_bag"}


def classify(name):
    """Return the role of a single object name, or None if it says nothing."""
    lowered = name.lower()
    for role, patterns in _ROLES:
        for pattern in patterns:
            if re.search(pattern, lowered):
                return role
    return None


def survey(objects):
    """Group mesh objects by role. Unrecognised names land under None."""
    found = {}
    for obj in objects:
        if obj.type != 'MESH':
            continue
        found.setdefault(classify(obj.name), []).append(obj)
    for group in found.values():
        group.sort(key=lambda o: -len(o.data.vertices))
    return found


def _densest(objects):
    return max(objects, key=lambda o: len(o.data.vertices)) if objects else None


def identify(objects):
    """Assign head / teeth / tongue from names.

    Returns ``(assignment, notes)``.  ``assignment['head']`` is None when the
    file is genuinely ambiguous -- the caller is expected to report ``notes``
    and refuse rather than fall back to a guess.
    """
    roles = survey(objects)
    notes = []

    named = roles.get("head") or []
    if len(named) == 1:
        head = named[0]
        notes.append("head: %r (matched by name)" % head.name)
    elif len(named) > 1:
        head = named[0]
        notes.append("head: %r (densest of %d name matches: %s)"
                     % (head.name, len(named),
                        ", ".join(o.name for o in named)))
    else:
        # Nothing named like a head. The densest mesh is a reasonable guess
        # ONLY once every object with a known non-head role is off the table.
        candidates = [o for role, group in roles.items()
                      if role not in NOT_HEAD for o in group]
        head = _densest(candidates)
        if head is None:
            notes.append("head: NONE -- every mesh in the file is named as "
                         "hair, teeth, tongue, eyes or brows")
        else:
            notes.append("head: %r (no mesh is named 'head' or 'face'; fell "
                         "back to the densest mesh that is not hair, teeth, "
                         "tongue, eyes or brows)" % head.name)

    teeth = []
    for role in ("upper_teeth", "lower_teeth", "teeth"):
        teeth.extend(o for o in roles.get(role, []) if o is not head)
    tongue = next((o for o in roles.get("tongue", []) if o is not head), None)

    if teeth:
        notes.append("teeth: %s" % ", ".join(o.name for o in teeth))
    else:
        notes.append("teeth: none found as separate objects (expected if they "
                     "are already shells of the head mesh)")
    notes.append("tongue: %s" % (tongue.name if tongue else "none found"))

    ignored = [o.name for role in sorted(NOT_HEAD - {"upper_teeth",
                                                     "lower_teeth", "teeth",
                                                     "tongue"})
               for o in roles.get(role, [])]
    if ignored:
        notes.append("left alone: %s" % ", ".join(ignored))
    unknown = [o.name for o in roles.get(None, []) if o is not head]
    if unknown:
        notes.append("unrecognised names: %s" % ", ".join(unknown))

    return {"head": head, "teeth": teeth, "tongue": tongue}, notes
