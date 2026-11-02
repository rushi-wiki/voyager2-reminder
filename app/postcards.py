from pathlib import Path

POSTCARD_DIR = Path(__file__).parent / "postcards"

# Each update shows the next card, so the archive unfolds over time. The first
# card is also used for milestone emails. Images are NASA/JPL (public domain).
GOLDEN_RECORD = {
    "image": "golden-record.jpg",
    "alt": "The Golden Record beside an illustration of a Voyager spacecraft",
    "title": "The message in a bottle",
    "story": (
        "Bolted to each Voyager is a 12-inch gold-plated record of images and "
        "sounds from Earth. Long after the spacecraft falls silent, it will "
        "keep carrying that greeting between the stars."
    ),
}

POSTCARDS = {
    "voyager_1": [
        {
            "image": "pale-blue-dot.jpg",
            "alt": "Earth as a tiny speck inside a band of scattered sunlight",
            "title": "The Pale Blue Dot",
            "story": (
                "That bright speck in the sunbeam is Earth. On Valentine's Day 1990, "
                "more than 4 billion miles from home, Voyager 1 turned around for one "
                "last family portrait of the planets. Soon after, its cameras were "
                "switched off for good."
            ),
        },
        {
            "image": "great-red-spot.jpg",
            "alt": "Swirling orange clouds around Jupiter's Great Red Spot",
            "title": "Inside Jupiter's storm",
            "story": (
                "On 25 February 1979, Voyager 1 caught the Great Red Spot in this "
                "much detail as it closed in on Jupiter, with wave patterns "
                "churning through the clouds beside it."
            ),
        },
        {
            "image": "crescent-saturn.jpg",
            "alt": "A dark Saturn seen as a thin crescent, with its shadow across the rings",
            "title": "A Saturn you can't see from Earth",
            "story": (
                "Four days after flying past, Voyager 1 looked back from 5.3 million km "
                "on 16 November 1980. Saturn appears as a crescent with its shadow "
                "falling across the rings, a view that's never possible from Earth."
            ),
        },
        GOLDEN_RECORD,
        {
            "image": "jupiter-io-europa.jpg",
            "alt": "Jupiter's clouds with the moons Io and Europa in front",
            "title": "Two moons, one planet",
            "story": (
                "On 13 February 1979, Voyager 1 framed Io and Europa against Jupiter's "
                "clouds. Io sits above the Great Red Spot, and Europa floats above "
                "the cloud tops to its right."
            ),
        },
        {
            "image": "voyager-1-launch.jpg",
            "alt": "A Titan-Centaur rocket lifting off in a cloud of exhaust",
            "title": "The one that left second",
            "story": (
                "Voyager 1 lifted off at 8:56 a.m. on 5 September 1977, 16 days after "
                "its twin. It took a faster route, and it's why the second one to "
                "launch carries the name Voyager 1."
            ),
        },
    ],
    "voyager_2": [
        {
            "image": "neptune-dark-spot.jpg",
            "alt": "Neptune in deep blue with its Great Dark Spot and white clouds",
            "title": "The planet only Voyager 2 has visited",
            "story": (
                "In 1989, Voyager 2 showed us Neptune's Great Dark Spot, with bright "
                "white clouds changing quickly around it. No spacecraft has been "
                "back since."
            ),
        },
        {
            "image": "neptune-triton.jpg",
            "alt": "Thin crescents of Neptune and its moon Triton against black space",
            "title": "The last planet, in the rear-view mirror",
            "story": (
                "About three days after its closest approach, Voyager 2 looked back at "
                "the crescents of Neptune and its largest moon, Triton. There were "
                "no more planets ahead."
            ),
        },
        GOLDEN_RECORD,
        {
            "image": "uranus-farewell.jpg",
            "alt": "A thin pale crescent of Uranus on a black background",
            "title": "Goodbye to Uranus",
            "story": (
                "On 25 January 1986, Voyager 2 recorded this pale crescent as it left "
                "Uranus behind. It remains the only spacecraft ever to have flown "
                "past the planet."
            ),
        },
        {
            "image": "voyager-2-launch.jpg",
            "alt": "A Titan-Centaur rocket rising from the launch pad",
            "title": "The one that left first",
            "story": (
                "Voyager 2 lifted off at 10:29 a.m. on 20 August 1977, 16 days before "
                "its twin. Its slower route opened the way to Uranus and Neptune, "
                "which no other spacecraft has reached."
            ),
        },
    ],
}

def postcard_for(spacecraft, count, milestone=False):
    cards = POSTCARDS[spacecraft]
    return cards[0] if milestone else cards[count % len(cards)]
