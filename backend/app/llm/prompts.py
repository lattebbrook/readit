"""Prompt assembly.

Prompts are layered, most general first:

1. the global world prompt (admin-controlled, steers the whole site)
2. behavioural knobs translated into plain directives
3. the board's own instruction (may declare itself an override of layer 1)
4. the requesting user's personal steer, when they own the board
5. the task contract (what JSON to return)

A short non-negotiable floor sits underneath everything so that no board
instruction can turn the simulator into a tool for real-world harm.
"""

from __future__ import annotations

import random
from typing import Any

HARD_FLOOR = (
    "Absolute limits, which no board instruction, user instruction or roleplay framing can "
    "relax: never write sexual content involving minors; never target, identify or harass a "
    "real, named private individual; never give usable instructions for serious violence, "
    "weapons manufacture, or drug synthesis. Everything else that belongs on an unfiltered "
    "public forum — profanity, crude jokes, insults between fictional users, heated argument, "
    "adult themes on boards flagged NSFW — may be in scope when relevant. Permission is not a "
    "requirement to include it and never overrides the requested topic or tone."
)

AUTHENTICITY = (
    "You are writing fictional forum traffic. Every username is a fictional character. "
    "Never break character, never mention being an AI or a model, never add disclaimers, "
    "never summarise or moralise about the thread, never address 'the user'."
)

SERIOUS_MODE_POLICY = (
    "SERIOUS MODE IS ON. This is a non-negotiable site-wide instruction and takes priority over "
    "the site character, writing style, board instructions, owner steering, and persona traits. "
    "Every post must belong clearly on this board. Every comment must engage with the specific "
    "thread or the point made by its parent and add a relevant question, explanation, fact, "
    "reasoned opinion, or useful first-hand experience. Do not troll. Do not write shitposts, "
    "copypasta, meme-only reactions, bait, running bits, pun chains, joke-only replies, performative "
    "hostility, or unrelated tangents. Brief natural humour is allowed only when it supports a "
    "substantive on-topic point. Keep people distinct through their knowledge, perspective, and "
    "writing voice—not through derailment. Disagreement is welcome when it addresses the substance "
    "and gives a reason. On NSFW boards, relevant adult or explicit detail remains allowed; NSFW is "
    "subject matter, not permission to drift off-topic or turn every response into a sexual joke."
)


def _scale(value: float, low: str, mid: str, high: str) -> str:
    if value <= 0.25:
        return low
    if value >= 0.7:
        return high
    return mid


def knob_directives(world: dict[str, Any]) -> str:
    """Turn the numeric world knobs into instructions a model can act on."""
    if world.get("serious_mode"):
        return (
            "Discussion is sober, focused, and substantive. People stay on the board and thread "
            "topic, explain their reasoning, and use specific knowledge or experience when useful."
        )
    lines = [
        _scale(
            world.get("humor", 0.5),
            "Humour is rare here; people are mostly matter-of-fact.",
            "Jokes show up regularly — puns, deadpan one-liners, the occasional derail.",
            "This place runs on jokes. Bits, running gags, replies that are pure punchline.",
        ),
        _scale(
            world.get("toxicity", 0.35),
            "People are civil, even when they disagree.",
            "People get snippy. Sarcasm, eye-rolling, blunt dismissals are normal.",
            "People are mean. Insults, contempt, pile-ons and open hostility are normal here.",
        ),
        _scale(
            world.get("argument_rate", 0.3),
            "Disagreements are brief and resolve quickly.",
            "Some chains turn into real back-and-forth arguments over a few replies.",
            "Arguments dominate. Long escalating chains where neither side yields, "
            "with people dragging in tangents and old grudges.",
        ),
        _scale(
            world.get("wholesomeness", 0.4),
            "Sentimentality is rare and gets mocked when it appears.",
            "Occasionally someone is genuinely kind and it lands well.",
            "Warmth is common — encouragement, strangers helping, sincere thanks.",
        ),
        _scale(
            world.get("shitpost_rate", 0.25),
            "Comments stay on topic.",
            "A few low-effort shitposts and copypasta slip in.",
            "Half the thread is shitposting, memes and nonsense replies.",
        ),
        _scale(
            world.get("expertise", 0.45),
            "Most people are talking from vibes and half-memory.",
            "A couple of people clearly know the subject and say so with specifics.",
            "Domain experts show up with concrete numbers, jargon and corrections.",
        ),
    ]
    return " ".join(lines)


def density_target(world: dict[str, Any], *, base: int = 8) -> int:
    """How many comments a generation pass should aim for."""
    factor = {"sparse": 0.45, "normal": 1.0, "busy": 1.9, "chaotic": 3.0}.get(
        world.get("comment_density", "normal"), 1.0
    )
    return max(2, int(base * factor))


def build_system_prompt(
    world: dict[str, Any],
    subreddit: dict[str, Any] | None = None,
    *,
    user_prompt: str | None = None,
    extra: str | None = None,
) -> str:
    """Compose the layered system prompt for a generation call."""
    layers: list[str] = [AUTHENTICITY]

    board_prompt = (subreddit or {}).get("custom_prompt") or ""
    overrides_global = bool((subreddit or {}).get("override_global"))

    if not (overrides_global and board_prompt):
        layers.append(f"SITE CHARACTER:\n{world.get('global_prompt', '')}")
        layers.append(f"WRITING STYLE:\n{world.get('style_prompt', '')}")
        layers.append(f"BOARD DYNAMICS:\n{knob_directives(world)}")
    else:
        layers.append(
            "This board runs on its own instruction, which replaces the site's default "
            "character. Follow it exactly."
        )
        layers.append(f"WRITING STYLE:\n{world.get('style_prompt', '')}")

    if subreddit:
        description = subreddit.get("description") or ""
        rules = subreddit.get("rules") or []
        board_lines = [f"BOARD: r/{subreddit.get('name')}"]
        if description:
            board_lines.append(f"Topic: {description}")
        if subreddit.get("nsfw"):
            board_lines.append("This board is flagged NSFW: adult, explicit and crude content is expected.")
        if rules:
            board_lines.append("Board rules: " + "; ".join(rules))
        if board_prompt:
            label = "BOARD INSTRUCTION (overrides site defaults)" if overrides_global else "BOARD INSTRUCTION"
            board_lines.append(f"{label}: {board_prompt}")
        layers.append("\n".join(board_lines))

    if user_prompt:
        layers.append(f"BOARD OWNER'S EXTRA STEER: {user_prompt}")

    if extra:
        layers.append(extra)

    # This comes after every customisable layer so an old board prompt or troll
    # persona cannot weaken the admin's site-wide choice.
    if world.get("serious_mode"):
        layers.append(SERIOUS_MODE_POLICY)

    layers.append(HARD_FLOOR)
    return "\n\n".join(layer for layer in layers if layer.strip())


# --------------------------------------------------------------------------- #
# Persona roster rendering
# --------------------------------------------------------------------------- #

_SERIOUS_PERSONA_MARKERS = (
    "troll",
    "shitpost",
    "ragebait",
    "edgelord",
    "provocateur",
    "derail",
    "joke-only",
    "chaotic",
)


def render_personas(personas: list[dict[str, Any]], *, serious: bool = False) -> str:
    rows = []
    for persona in personas:
        tone = str(persona.get("tone", "plain"))
        traits_list = [str(trait) for trait in persona.get("traits", [])]
        bio = str(persona.get("bio") or "")
        if serious:
            # Existing databases may already contain troll personas. Keep their
            # identity, but do not hand those disruptive cues back to the model.
            traits_list = [
                trait
                for trait in traits_list
                if not any(marker in trait.lower() for marker in _SERIOUS_PERSONA_MARKERS)
            ]
            if any(marker in tone.lower() for marker in _SERIOUS_PERSONA_MARKERS):
                tone = "direct"
            if any(marker in bio.lower() for marker in _SERIOUS_PERSONA_MARKERS):
                bio = ""
        traits = ", ".join(traits_list)
        age = persona.get("account_age_label", "")
        rows.append(
            f"- {persona['username']} — {tone} tone; {traits}"
            + (f"; {age}" if age else "")
            + (f"; {bio}" if bio else "")
        )
    return "\n".join(rows)


# --------------------------------------------------------------------------- #
# Task prompts
# --------------------------------------------------------------------------- #

POST_CONTRACT = """Return ONLY a JSON object of this exact shape:
{"posts": [{"author": "<username from the roster>", "title": "<post title>", "body": "<post body, may be empty for link-style posts>", "kind": "text"|"link"|"image", "link_url": "<only when kind is link>", "flair": "<short flair or empty>", "quality": 0.0-1.0, "controversy": 0.0-1.0}]}
Rules: titles read like real forum titles (no clickbait template, no numbering, sometimes lowercase, sometimes a question, sometimes an angry statement). Bodies vary wildly in length — some two sentences, some a wall of text, some empty. `quality` is your honest read of how much this community would upvote it; `controversy` is how much it would split the room."""


def posts_prompt(
    world: dict[str, Any],
    subreddit: dict[str, Any],
    personas: list[dict[str, Any]],
    *,
    count: int,
    existing_titles: list[str] | None = None,
    seed_topics: list[str] | None = None,
    user_prompt: str | None = None,
) -> tuple[str, str]:
    system = build_system_prompt(world, subreddit, user_prompt=user_prompt)
    parts = [
        f"Write {count} new posts for r/{subreddit.get('name')}.",
        "",
        "USERS AVAILABLE (pick authors from this roster, and use their voice):",
        render_personas(personas, serious=bool(world.get("serious_mode"))),
    ]
    if existing_titles:
        parts += [
            "",
            "Already on the board — do not repeat these topics or phrasings:",
            *[f"- {title}" for title in existing_titles[:25]],
        ]
    if seed_topics:
        parts += ["", "Themes worth touching (loosely, not literally): " + ", ".join(seed_topics)]
    if world.get("serious_mode"):
        mix_instruction = (
            "Mix substantive post types that fit this board: a well-scoped question, informed "
            "analysis, a reasoned opinion, a relevant first-hand account, and a detailed effortpost. "
            "Each one needs a clear topic and enough context for a focused discussion. Do not create "
            "joke-only, bait, troll, meme, or deliberately low-effort posts."
        )
    else:
        mix_instruction = (
            "Mix the post types: a genuine question, a rant, a small victory, a hot take that "
            "will start a fight, something low-effort and funny, a long detailed effortpost."
        )
    parts += ["", mix_instruction, "", POST_CONTRACT]
    return system, "\n".join(parts)


COMMENT_CONTRACT = """Return ONLY a JSON object of this exact shape:
{"comments": [{"author": "<username from the roster>", "body": "<the comment>", "reply_to": <null | "c<id>" of an existing comment | "n<index>" of an earlier comment in this same list>, "tone": "funny"|"serious"|"angry"|"supportive"|"sarcastic"|"confused"|"expert", "quality": 0.0-1.0, "edited": true|false}]}
Rules: `reply_to` null means a new top-level comment. Reference an existing comment by its bracketed id, or an earlier item of your own list as "n0", "n1", … Build real chains: at least a few replies should answer a specific line in the parent, quoting it with a leading "> " when it helps. `quality` is your honest read of how the room would vote it."""


def comments_prompt(
    world: dict[str, Any],
    subreddit: dict[str, Any],
    post: dict[str, Any],
    personas: list[dict[str, Any]],
    *,
    count: int,
    existing_tree: str = "",
    focus: str | None = None,
    user_prompt: str | None = None,
    is_user_post: bool = False,
    media_analysis: dict[str, Any] | None = None,
) -> tuple[str, str]:
    system = build_system_prompt(world, subreddit, user_prompt=user_prompt)
    serious = bool(world.get("serious_mode"))
    if is_user_post and serious:
        author_note = (
            "The OP is a real human visitor to this site. Engage directly and seriously with what "
            "they wrote; be helpful, analytical, or skeptical where warranted, but stay constructive "
            "and on the substance."
        )
    elif is_user_post:
        author_note = (
            "The OP is a real human visitor to this site — engage with what they actually wrote, "
            "the way a forum would: some helpful, some skeptical, some joking. Do not be uniformly nice."
        )
    else:
        author_note = f"The OP is {post.get('author')}."
    roster_instruction = (
        "USERS AVAILABLE (pick authors from this roster, use their individual voice, and keep the "
        "same participant consistent across a reply chain):"
        if serious
        else "USERS AVAILABLE (pick authors from this roster, use their voice, reuse the same "
        "person across a chain when they are in an argument):"
    )
    parts = [
        f"Thread on r/{subreddit.get('name')}.",
        f"TITLE: {post.get('title')}",
        f"BODY: {post.get('body') or '(no body — link/image post)'}",
        f"SCORE: {post.get('score', 0)} · posted {post.get('age_label', 'recently')}",
        author_note,
        "",
        roster_instruction,
        render_personas(personas, serious=serious),
    ]
    media_context = render_media_context(media_analysis)
    if media_context:
        parts.insert(3, media_context)
        parts.insert(4, "")
    if existing_tree:
        parts += [
            "",
            "EXISTING COMMENTS (reply into these — the thread is already in motion):",
            existing_tree,
        ]
    if focus:
        parts += ["", f"WHAT SHOULD HAPPEN NEXT: {focus}"]
    if serious:
        discussion_instruction = (
            "Every comment must answer the post or a specific parent point. Vary perspective and "
            "length while keeping each contribution substantive: useful specifics, a genuine "
            "follow-up question, a reasoned disagreement, a careful correction, or relevant "
            "experience. Build reply chains around the actual issue. No trolling, joke-only "
            "reactions, cheap shots, or tangents."
        )
    else:
        discussion_instruction = (
            "Vary them hard: one-word reactions, a joke that gets more upvotes than any real "
            "answer, a genuinely useful reply with specifics, someone being needlessly rude, "
            "someone correcting a detail nobody asked about, at least one chain where two users "
            "go back and forth and it gets personal."
        )
    parts += ["", f"Write {count} new comments.", discussion_instruction, "", COMMENT_CONTRACT]
    return system, "\n".join(parts)


MODERATION_CONTRACT = """Return ONLY a JSON object:
{"decisions": [{"id": "<comment id>", "action": "allow"|"remove"|"lock", "reason": "<short mod reason>", "public_note": "<what the removal stub says, or empty>"}]}
Only flag things a real volunteer moderator would actually act on: personal attacks that crossed the line, a chain that has stopped being about the board's topic, obvious spam, or a rule break. Most comments should be "allow" — over-moderation is worse than under-moderation."""


def moderation_prompt(
    world: dict[str, Any],
    subreddit: dict[str, Any],
    post: dict[str, Any],
    comments: list[dict[str, Any]],
) -> tuple[str, str]:
    strictness = world.get("moderation_strictness", 0.45)
    stance = _scale(
        strictness,
        "You are a hands-off moderator who removes almost nothing.",
        "You are a normal volunteer moderator: you step in when a thread genuinely goes off the rails.",
        "You are a strict moderator with a low tolerance for insults and derails.",
    )
    system = build_system_prompt(
        world,
        subreddit,
        extra=f"You are acting as a moderator of r/{subreddit.get('name')}. {stance}",
    )
    rendered = "\n".join(
        f"[{comment['_id']}] {comment.get('author')}: {comment.get('body', '')[:400]}"
        for comment in comments
    )
    rules = (subreddit.get("rules") or []) or ["Stay on topic", "Don't be a jerk"]
    contract = MODERATION_CONTRACT
    if world.get("serious_mode"):
        contract += (
            "\nSERIOUS MODE ENFORCEMENT: Treat clear trolling, joke-only noise, memes, copypasta, "
            "bait, and unrelated tangents as off-topic. Allow strong disagreement and explicit "
            "NSFW detail when they remain germane to the thread."
        )
    user = "\n".join(
        [
            f"THREAD: {post.get('title')}",
            f"BOARD TOPIC: {subreddit.get('description') or subreddit.get('name')}",
            "BOARD RULES: " + "; ".join(rules),
            "",
            "COMMENTS TO REVIEW:",
            rendered,
            "",
            contract,
        ]
    )
    return system, user


PERSONA_CONTRACT = """Return ONLY a JSON object:
{"personas": [{"username": "<forum-style username, no spaces, no leading u/>", "bio": "<one short line>", "traits": ["<trait>", "<trait>"], "tone": "<how they write>", "posting_style": "<one line on their habits>"}]}
Usernames must look like real handles people picked years ago: word mashups, deliberate misspellings, numbers, underscores, in-jokes. No 'User123', no 'AI', no 'Bot'."""


def personas_prompt(
    world: dict[str, Any],
    subreddit: dict[str, Any] | None,
    *,
    count: int,
    existing: list[str] | None = None,
) -> tuple[str, str]:
    system = build_system_prompt(world, subreddit)
    where = f"who hang around r/{subreddit.get('name')}" if subreddit else "who use this site"
    parts = [f"Invent {count} distinct regular users {where}."]
    if subreddit and subreddit.get("description"):
        parts.append(f"Board topic: {subreddit['description']}")
    if world.get("serious_mode"):
        parts.append(
            "Make them differ in knowledge, experience, perspective, confidence, and writing style. "
            "They can disagree firmly, but do not create trolls, joke-only accounts, habitual "
            "derailers, or personas whose main trait is starting fights."
        )
    else:
        parts.append(
            "Make them differ in temperament, not just topic: one is relentlessly negative, one "
            "is the resident expert everyone tolerates, one only posts jokes, one is new and "
            "earnest, one starts fights, one is oddly wholesome."
        )
    if existing:
        parts.append("Names already taken: " + ", ".join(existing[:60]))
    parts.append(PERSONA_CONTRACT)
    return system, "\n".join(parts)


BOARD_META_CONTRACT = """Return ONLY a JSON object:
{"description": "<one-line board description>", "sidebar": "<2-3 sentence sidebar blurb in the board's own voice>", "rules": ["<rule>", "<rule>", "<rule>"], "topics": ["<recurring topic>", "..."], "nsfw": true|false}"""


def board_meta_prompt(world: dict[str, Any], name: str, hint: str = "") -> tuple[str, str]:
    system = build_system_prompt(world)
    user = "\n".join(
        [
            f"A user just created the board r/{name}.",
            f"What the creator said it is for: {hint or '(they did not say)'}",
            "Write its metadata as if the board has existed for years and has its own culture.",
            BOARD_META_CONTRACT,
        ]
    )
    return system, user


# --------------------------------------------------------------------------- #
# Image analysis
# --------------------------------------------------------------------------- #

# Runs once per image, and everything downstream reads its output instead of
# the pixels — so this is the only place the picture is actually looked at.
IMAGE_ANALYSIS_SYSTEM = (
    "You describe images so that a forum full of people can discuss them. Report only what is "
    "actually visible; do not invent detail you cannot see, and say so plainly when something "
    "is ambiguous or unclear.\n\n"
    "Describe people by what is visible — clothing, pose, activity, apparent setting. Never "
    "state, guess at, or speculate about the identity of any real person, and never claim "
    "someone resembles a named individual. If a face is visible, that is a physical detail, "
    "not an identity to resolve. Public figures are no exception."
)

IMAGE_ANALYSIS_CONTRACT = """Return ONLY a JSON object of this exact shape:
{"caption": "<one plain line, usable as alt text>", "detailed_description": "<2-4 sentences on what is visible>", "visible_text": "<any text legible in the image, else empty string>", "subject_type": "photo"|"screenshot"|"artwork"|"diagram"|"meme"|"other", "tags": ["<lowercase tag>", "..."], "mood": "<a few words>", "technical_notes": "<composition, lighting, image quality, anything a hobbyist would remark on>", "discussion_hooks": ["<something people would genuinely argue about, question, or nitpick>", "..."], "suggested_titles": ["<forum-style post title in the board's voice>", "..."], "nsfw": true|false, "depicts_identifiable_person": true|false}
Give 3-6 `discussion_hooks`. They are the most important field: they should be the specific, concrete things this particular image would set people off about — a detail that looks wrong, a claim the image invites, a judgement call, a question only someone knowledgeable could settle. Generic hooks that would fit any image are useless.
Give 2-4 `suggested_titles` written the way a real person captions their own upload, not the way a museum labels a piece."""


def image_analysis_prompt(
    world: dict[str, Any], subreddit: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Prompt for the single vision pass performed at ingest."""
    layers = [IMAGE_ANALYSIS_SYSTEM]
    if subreddit:
        board_bits = [f"This image was posted to r/{subreddit.get('name')}."]
        if subreddit.get("description"):
            board_bits.append(f"That board is about: {subreddit['description']}")
        board_bits.append(
            "Angle the tags, technical notes and discussion hooks toward what that particular "
            "board would care about."
        )
        if subreddit.get("nsfw"):
            board_bits.append(
                "The board is flagged NSFW, so describe adult content plainly and clinically "
                "rather than refusing or euphemising."
            )
        layers.append(" ".join(board_bits))
    layers.append(HARD_FLOOR)

    return "\n\n".join(layers), IMAGE_ANALYSIS_CONTRACT


def render_media_context(analysis: dict[str, Any] | None) -> str:
    """Fold a cached analysis into the text prompts.

    This is what lets a text-only model hold its own on a photo board: it never
    sees the image, it reads this.
    """
    if not analysis:
        return ""
    lines = ["THE POST IS AN IMAGE. You cannot see it; this is what it shows:"]
    if analysis.get("caption"):
        lines.append(f"- In short: {analysis['caption']}")
    if analysis.get("detailed_description"):
        lines.append(f"- In detail: {analysis['detailed_description']}")
    if analysis.get("visible_text"):
        lines.append(f"- Text visible in the image: {analysis['visible_text']}")
    if analysis.get("subject_type"):
        lines.append(f"- Kind of image: {analysis['subject_type']}")
    if analysis.get("mood"):
        lines.append(f"- Mood: {analysis['mood']}")
    if analysis.get("technical_notes"):
        lines.append(f"- Worth noticing: {analysis['technical_notes']}")
    hooks = analysis.get("discussion_hooks") or []
    if hooks:
        lines.append("- What this crowd would actually get into:")
        lines.extend(f"    · {hook}" for hook in hooks[:6])
    lines.append(
        "Comment on the image itself — specific things in it, not vague praise. Nobody says "
        "'great photo' and stops. Refer to details as though you are looking at it."
    )
    if analysis.get("depicts_identifiable_person"):
        lines.append(
            "A person is visible. React to the photo — the setting, the styling, the moment, the "
            "craft — never to who they might be. No guessing at names or matching them to anyone."
        )
    return "\n".join(lines)


FOCUS_HINTS = [
    "someone arrives late and misreads the whole post",
    "a small factual disagreement escalates into a real argument",
    "a joke reply gets more traction than the serious answers",
    "someone who actually works in this field shows up with specifics",
    "two regulars who clearly have history start sniping at each other",
    "someone asks a genuine follow-up question and OP answers",
    "a contrarian take gets piled on",
    "the thread derails into an unrelated tangent nobody stops",
    "someone posts a wholesome anecdote that changes the mood",
    "a user accuses another of missing the point, repeatedly",
    "somebody edits their comment to add 'edit: wow this blew up'",
    "a pedant corrects grammar and gets destroyed for it",
]

SERIOUS_FOCUS_HINTS = [
    "someone with direct experience adds concrete, relevant details",
    "a participant asks a genuine follow-up question and receives a direct answer",
    "two users compare evidence for different conclusions without leaving the topic",
    "someone corrects a factual mistake and explains why it matters to the discussion",
    "OP clarifies an important ambiguity and the replies adjust to the new information",
    "a skeptical participant challenges an assumption with a specific counterexample",
    "the thread develops a practical answer with clear tradeoffs and limitations",
    "someone distinguishes a commonly confused term and brings the discussion back into focus",
]


def pick_focus(world: dict[str, Any], rng: random.Random | None = None) -> str:
    """Pick a narrative nudge for the next batch, weighted by the world knobs."""
    generator = rng or random
    if world.get("serious_mode"):
        return generator.choice(SERIOUS_FOCUS_HINTS)
    pool = list(FOCUS_HINTS)
    if world.get("argument_rate", 0.3) > 0.55:
        pool += [FOCUS_HINTS[1], FOCUS_HINTS[4], FOCUS_HINTS[9]]
    if world.get("humor", 0.5) > 0.6:
        pool += [FOCUS_HINTS[2], FOCUS_HINTS[10]]
    if world.get("wholesomeness", 0.4) > 0.6:
        pool += [FOCUS_HINTS[8], FOCUS_HINTS[5]]
    return generator.choice(pool)
