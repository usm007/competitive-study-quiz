"""Phase 1 fixture maker, part 1: large synthetic study document + inventory.

Builds a dense, multi-section competitive-exam-style document for the
fictional Republic of Kamarupa (synthetic content, labelled as such),
plus:
  - longdoc_source.md       (the document, ~100 pages by ingest paging)
  - manifest.json           (expected examinable facts + loss-trap labels)
  - inventory.json          (full reference knowledge inventory)
  - inventory_firstpass.json (full minus 5 trap KUs -> second-pass demo)
  - inventory_diff.json      (5 resolved additions + 3 rejected candidates)
  - ignored_anchors.json     (table_header / formatting_artifact only)

Anchor hygiene: padding prose and headings contain NO anchor patterns
(no digits, no consecutive capitals, no refs, no percentages, no formulas).
Every other anchor must be covered by KU text or explicitly ignored.

Usage:
  py scripts/make_longdoc_fixture.py --out tests/fixtures/longdoc
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_common import load_json, save_json, ensure_dir, fail, run_main
import anchors as anchors_mod


# ---------------------------------------------------------------- pools
# Anchor-safe padding: no digits, no %, no =, no 2+ consecutive capitals,
# no ALLCAPS, no bare proper-noun pairs.
PADDING = [
    "The paragraphs that follow introduce the central theme of this chapter in broad and general terms. "
    "Readers who are already familiar with the background may move ahead to the detailed discussion below, "
    "where each point is stated precisely and supported with exact figures. The summary at the end of the "
    "chapter collects the main ideas for quick reference during revision.",

    "Before turning to exact provisions and figures, it is useful to keep the overall picture in mind. "
    "The sections below move from general principles to particular details, and later chapters build upon "
    "the foundation laid here. While reading, pay attention to headings, because each heading marks a shift "
    "from one examinable idea to the next.",

    "Much of what follows is descriptive rather than argumentative. The aim is to record what the provisions "
    "state, how the institutions are arranged, and which figures the official releases report. Where an "
    "exception applies, it is stated separately at the end of the relevant passage so that it is not confused "
    "with the general rule.",

    "Students are advised to read slowly through the dense passages and to mark every date, name and figure "
    "as they go. The habit of converting each underlined item into a single question will repay the effort "
    "during revision. Cross references point to related material discussed in other chapters.",

    "The discussion below assumes no prior specialised knowledge and builds each idea from first principles. "
    "Longer passages alternate with compact lists and summaries of figures so that different kinds of material "
    "remain visually distinct. Footnotes carry qualifications that change the meaning of the main rule.",

    "It is easy to skim through familiar sounding material, so the text deliberately slows down at points of "
    "detail. Names that look alike are placed side by side on purpose, and the surrounding sentences explain "
    "how their roles differ. Such pairs deserve special attention because examinations test them together.",
]

LOW_VALUE_BRIDGE = (
    "The intervening exposition rehearses background that carries little direct examination weight, "
    "restating familiar context at length before the next examinable point arrives. "
    "Patient readers will find that the substance resumes shortly, with exact provisions following "
    "the general commentary without further delay."
)

VOLUME_SCALE = 5

# Combinatorial filler: all slots lowercase, isolated proper nouns only.
TRACTS = ["eastern bils", "western uplands", "southern plateaus", "central trough",
          "northern dunes", "coastal fringe", "riverine chars", "forest fringe",
          "hill slopes", "valley floor", "market towns", "ferry ghats"]
TOPICS = ["settlement pattern", "drainage habit", "soil texture", "crop calendar",
          "ferry traffic", "market days", "craft tradition", "festival round",
          "school attendance", "cattle movement", "fish catch", "bamboo harvest"]
WORDS = ["twelve", "thirty", "forty", "twenty", "fifteen", "fifty", "sixty",
         "eighty", "ninety", "hundred"]

FILLER_TMPL = [
    "The {topic} of the {tract} changes slowly from season to season, and elders in the {tract2} recall "
    "earlier habits that the young have partly set aside. Surveyors who walk the {tract} note small "
    "differences between neighbouring hamlets, though the broad routine stays recognisable across the "
    "whole belt. Such local colour fills the gazetteer without adding to the examinable record.",

    "Gazetteer entries for the {tract} dwell at length upon the {topic}, describing tools, timings and "
    "customary shares in prose that rewards only the most patient reader. The {tract2} receives similar "
    "treatment in the following pages, with anecdotes of fairs and ferries that illustrate daily life "
    "rather than testable fact. Examiners have never drawn upon this descriptive padding.",

    "Revenue reports devote several pages to the {topic} of the {tract}, tabulating nothing of consequence "
    "and concluding that conditions remain broadly stable. The {tract2} is described in nearly identical "
    "terms a chapter later, which suggests how little weight such passages carry. Readers may skim these "
    "stretches and reserve close attention for the dated provisions that follow.",

    "Travellers accounts of the {tract} praise the {topic} in language that runs on for paragraphs without "
    "stating a single figure or name worth remembering. The same can be said of the notes on the {tract2}, "
    "where the narrative lingers over scenery and routine. These stretches test stamina rather than memory, "
    "and the examination syllabus passes over them in silence.",
]


def gen_filler(i):
    t = FILLER_TMPL[i % len(FILLER_TMPL)]
    return t.format(topic=TOPICS[(i * 3) % len(TOPICS)],
                    tract=TRACTS[(i * 5) % len(TRACTS)],
                    tract2=TRACTS[(i * 5 + 4) % len(TRACTS)])


# ---------------------------------------------------------------- model
class Doc:
    def __init__(self):
        self.lines = []
        self.facts = []   # fact specs in document order
        self.headers = []  # table header cell lists (for ignored anchors)
        self.n = 0

    def add(self, text):
        self.lines.append(text)

    def blank(self):
        self.lines.append("")

    def heading(self, level, text):
        self.add("#" * level + " " + text)
        self.blank()

    def para(self, text):
        self.add(text)
        self.blank()

    def fact(self, trap, section, subtopic, kutype, tier, text, stmt=None,
             conf=None, cluster=None, related=(), cogn=None, extra_dims=None,
             emit=True):
        self.n += 1
        fid = "F-%04d" % self.n
        self.facts.append({
            "fid": fid, "trap": trap, "section": section, "subtopic": subtopic,
            "kutype": kutype, "tier": tier, "text": text,
            "stmt": stmt or text, "conf": conf, "cluster": cluster,
            "related": list(related), "cogn": cogn,
            "extra_dims": extra_dims or {},
        })
        if emit:
            self.para(text)
        return fid

    def emit_para_facts(self, sentences):
        self.para(" ".join(sentences))

    def bullet_list(self, items):
        for it in items:
            self.add("- " + it)
        self.blank()

    def table(self, header, rows):
        self.headers.append(list(header))
        self.add("| " + " | ".join(header) + " |")
        self.add("| " + " | ".join(["---"] * len(header)) + " |")
        for r in rows:
            self.add("| " + " | ".join(r) + " |")
        self.blank()

    def footnote(self, text):
        self.para("A note on exceptions and qualifications: " + text)

    def text(self):
        return "\n".join(self.lines).rstrip() + "\n"


def pad(doc, slug, k):
    # VOLUME_SCALE inflates low-value prose to long-document volume while
    # fact density stays proportional (density/skew checks are relative).
    for i in range(k * VOLUME_SCALE):
        if i % 3 == 2:
            doc.para(PADDING[(i + len(slug)) % len(PADDING)])
        elif i % 7 == 6:
            doc.para(LOW_VALUE_BRIDGE)
        else:
            doc.para(gen_filler(i * 7 + len(slug) * 13))


# ================================================================ content
def build_sections(doc):
    S1 = "Constitutional framework of the republic"
    doc.heading(1, "Study notes on the republic of Kamarupa")
    doc.para("These notes collect the examinable core of polity, history, geography, economy and culture "
             "for preliminary examinations. All persons, places, figures and provisions below belong to the "
             "synthetic setting and are used only to test the study pipeline.")
    doc.blank()
    # ---- section 1 ----
    doc.heading(1, S1)
    pad(doc, S1, 14)
    doc.heading(2, "Adoption and commencement of the charter")
    doc.fact("buried_paragraph", S1, "adoption", "date", 1,
             "After three years of deliberation in the constituent assembly, the Charter of the republic "
             "of Kamarupa was adopted on 14 March 1963, a date distinguished from the commencement that "
             "followed nearly a year later.",
             stmt="The Charter of the republic of Kamarupa was adopted on 14 March 1963.")
    pad(doc, S1, 4)
    s1a = "The Charter was adopted in 1963."
    s1b = "The Charter commenced on 2 January 1964."
    s1c = "The drafting committee was chaired by Jonali Das."
    doc.fact("compound_sentence", S1, "adoption", "date", 1, s1a, emit=False)
    doc.fact("compound_sentence", S1, "commencement", "date", 1, s1b, emit=False)
    doc.fact("compound_sentence", S1, "drafting", "person", 2, s1c, emit=False)
    doc.emit_para_facts([s1a, s1b, s1c])
    pad(doc, S1, 6)
    doc.heading(2, "Charter of rights in brief")
    doc.fact("plain", S1, "rights", "article", 1,
             "Article 14 of the Charter guarantees equality before the law to every person.",
             stmt="Article 14 guarantees equality before the law.")
    doc.fact("plain", S1, "rights", "article", 2,
             "Article 15 bars discrimination on the grounds of birth, kinship, faith, domicile or means.",
             stmt="Article 15 bars discrimination on grounds of birth, kinship, faith, domicile or means.")
    doc.fact("plain", S1, "rights", "article", 2,
             "Article 21 protects life and personal liberty, and no person is deprived except by just law.",
             stmt="Article 21 protects life and personal liberty.")
    art_rows = [
        ["Article 12", "Definition of the state", "4 clauses"],
        ["Article 13", "Laws repugnant to rights", "3 clauses"],
        ["Article 16", "Equality in public service", "5 clauses"],
        ["Article 19", "Six basic freedoms", "6 clauses"],
        ["Article 25", "Freedom of conscience", "2 clauses"],
        ["Article 32", "Remedies for rights", "4 clauses"],
        ["Article 40", "Village councils", "1 clause"],
        ["Article 51", "Promotion of peace", "1 clause"],
    ]
    doc.table(["Charter article", "Subject matter", "Length in clauses"], art_rows)
    for art, subj, ln in art_rows:
        doc.fact("table_cell", S1, "articles table", "table_value",
                 2 if art in ("Article 12", "Article 19", "Article 32") else 3,
                 "%s | %s | %s" % (art, subj, ln),
                 stmt="The table records that %s covers %s in %s." % (art, subj.lower(), ln),
                 emit=False)
    doc.fact("plain", S1, "remedies", "definition", 3,
             "The Charter lists eight writs for the enforcement of rights.")
    writs = [
        "The writ of habeas corpus secures release from unlawful custody.",
        "The writ of mandamus commands a public body to perform its duty.",
        "The writ of prohibition restrains a lower forum from excess of jurisdiction.",
        "The writ of certiorari quashes orders passed with error apparent.",
        "The writ of quo warranto questions unlawful occupation of public office.",
        "The writ of certiorari before judgment transfers a pending matter upward.",
        "The writ of review petition lies against orders passed without hearing.",
        "The writ of curative appeal lies after dismissal of a review petition.",
    ]
    for i, w in enumerate(writs):
        doc.fact("long_list_item" if i == 6 else "plain", S1, "remedies", "list_item",
                 2 if i == 6 else 3, "- " + w, stmt=w, emit=False)
    doc.bullet_list(writs)
    doc.footnote("The right against preventive custody under Article 22 does not extend to persons held "
                 "under a wartime detention ordinance, which is the sole exception to the custody code.")
    doc.fact("footnote_exception", S1, "custody exception", "exception", 2,
             "The right against preventive custody under Article 22 does not extend to persons held "
             "under a wartime detention ordinance, which is the sole exception to the custody code.",
             stmt="Preventive custody rights do not extend to persons held under a wartime detention ordinance.",
             emit=False)
    doc.heading(2, "Directive maxims and their place")
    doc.fact("split_distinction", S1, "maxims", "definition", 1,
             "The directive maxims of Part Four are guides for lawmaking and are not enforceable in any court.",
             stmt="The directive maxims of Part Four are not enforceable in any court.")
    pad(doc, S1, 5)
    doc.fact("split_distinction", S1, "maxims contrast", "comparison", 1,
             "Unlike the enforceable rights of Part Three, the maxims of Part Four guide the state without "
             "creating claims that citizens can press in court.",
             stmt="Part Three rights are enforceable while Part Four maxims are not.",
             conf="G-rights", cluster="CL-rights")
    doc.heading(2, "Amendments to the charter")
    amendments = [
        ("1965", "First Amendment", "added the Ninth Schedule of protected land laws"),
        ("1968", "Second Amendment", "revised the quorum of the upper house to forty members"),
        ("1971", "Third Amendment", "inserted Article 16A on service tribunals"),
        ("1974", "Fourth Amendment", "curtailed appeals in revenue matters"),
        ("1979", "Fifth Amendment", "deleted the right to holdpton as a charter right"),
        ("1984", "Sixth Amendment", "lowered the voting age to eighteen years"),
        ("1991", "Seventh Amendment", "created the inter-state river board"),
        ("2002", "Eighth Amendment", "inserted Article 21A on free schooling for ages six to fourteen"),
    ]
    for j, (yr, name, change) in enumerate(amendments):
        doc.fact("distributed_chronology" if j == 0 else "plain", S1, "amendments", "amendment",
                 1 if yr in ("1965",) else 2,
                 "- The %s of %s %s." % (name, yr, change),
                 stmt="The %s (%s) %s." % (name, yr, change), emit=False)
    doc.bullet_list(["The %s of %s %s." % (name, yr, change) for yr, name, change in amendments])
    doc.fact("repeated_detail", S1, "charter size", "number_value", 3,
             "The Charter originally contained two hundred and ninety articles, a count that later grew "
             "through amendment.",
             stmt="The Charter originally contained two hundred and ninety articles.")
    pad(doc, S1, 12)

    # ---- section 2 (short but dense) ----
    S2 = "Chronology of the freedom movement"
    doc.heading(1, S2)
    pad(doc, S2, 5)
    events = [
        ("1905", "the partition proclamation divided the eastern districts"),
        ("1911", "the proclamation was annulled after six years of protest"),
        ("1919", "the hartal movement shut the river ports for eleven days"),
        ("1927", "the civil disobedience march reached Chandrapur on foot"),
        ("1931", "the round table talks admitted two delegates from Kamarupa"),
        ("1935", "the provincial statute granted a limited franchise"),
        ("1942", "the quit dominion resolution was passed at Mornoi"),
        ("1947", "the dominion office transferred power at midnight"),
        ("1950", "the first general roll listed four lakh voters"),
        ("1955", "the linguistic survey recorded nine mother tongues"),
        ("1960", "the statehood commission began its sittings"),
        ("1963", "the republic came into being with the Charter"),
    ]
    for yr, ev in events:
        doc.fact("distributed_chronology", S2, "timeline", "date", 1 if yr in ("1947", "1963", "1942") else 2,
                 "- In %s, %s." % (yr, ev),
                 stmt="In %s, %s." % (yr, ev), emit=False)
    doc.bullet_list(["In %s, %s." % (yr, ev) for yr, ev in events])
    t2a = "The midnight transfer of 1947 lasted forty minutes."
    t2b = "The first general roll named four lakh voters across nine districts."
    t2c = "The survey of 1955 recorded nine mother tongues in thirty villages."
    doc.fact("compound_sentence", S2, "transfer detail", "number_value", 2, t2a, emit=False)
    doc.fact("compound_sentence", S2, "roll detail", "number_value", 3, t2b, emit=False)
    doc.fact("compound_sentence", S2, "survey detail", "number_value", 3, t2c, emit=False)
    doc.emit_para_facts([t2a, t2b, t2c])
    pad(doc, S2, 6)

    # ---- section 3 ----
    S3 = "River systems and surface water"
    doc.heading(1, S3)
    pad(doc, S3, 12)
    doc.heading(2, "The great rivers and their dams")
    river_rows = [
        ["Meyong", "2900", "Barun dam"],
        ["Sonai", "2840", "Baruni barrage"],
        ["Tirung", "1210", "Sailung dam"],
        ["Saimang", "980", "Kopru weir"],
        ["Nongri", "760", "Nongri anicut"],
        ["Diplai", "640", "Diplai gates"],
        ["Mornoi", "520", "Mornoi bund"],
        ["Umsai", "410", "Umsai sluice"],
    ]
    doc.table(["River name", "Length in kilometres", "Principal work"], river_rows)
    for name, ln, work in river_rows:
        doc.fact("table_cell", S3, "rivers table", "table_value", 1,
                 "%s | %s | %s" % (name, ln, work),
                 stmt="The %s river runs %s kilometres and is harnessed by the %s." % (name, ln, work),
                 emit=False)
    doc.fact("confusable_pair", S3, "meyong vs sonai", "comparison", 1,
             "The Meyong and the Sonai look alike on maps, but the Meyong is the longer river at 2900 "
             "kilometres against the Sonai at 2840 kilometres.",
             stmt="The Meyong at 2900 kilometres is longer than the Sonai at 2840 kilometres.",
             conf="G-rivers", cluster="CL-rivers")
    doc.fact("confusable_pair", S3, "barun vs baruni", "comparison", 1,
             "The Barun dam on the Meyong stores water, while the Baruni barrage on the Sonai only diverts "
             "water for canals without storage.",
             stmt="The Barun dam stores water while the Baruni barrage only diverts water.",
             conf="G-rivers", cluster="CL-rivers")
    pad(doc, S3, 6)
    doc.heading(2, "Tributaries worth naming")
    tribs = [
        ("Rongli", "180"), ("Hatola", "165"), ("Borjhar", "150"), ("Simlaguri", "140"),
        ("Borghat", "120"), ("Nalbari", "110"), ("Pathsala", "95"), ("Tihu", "80"), ("Boko", "60"),
    ]
    for name, ln in tribs:
        doc.fact("long_list_item", S3, "tributaries", "list_item", 3,
                 "- The %s tributary runs %s kilometres before joining the Meyong." % (name, ln),
                 stmt="The %s tributary runs %s kilometres before joining the Meyong." % (name, ln),
                 emit=False)
    doc.bullet_list(["The %s tributary runs %s kilometres before joining the Meyong." % (n, l) for n, l in tribs])
    doc.fact("buried_paragraph", S3, "discharge", "number_value", 2,
             "Amid the general description of ferries, markets and sandbanks, the survey records one exact "
             "figure that examinations repeat: the Meyong carries a mean discharge of forty thousand cusecs "
             "at Chandrapur in the month of August.",
             stmt="The Meyong carries a mean discharge of forty thousand cusecs at Chandrapur in August.")
    doc.fact("repeated_detail", S3, "baruni diversion", "number_value", 2,
             "The Baruni barrage diverts Sonai water for the eastern canals.",
             stmt="The Baruni barrage diverts Sonai water for the eastern canals.")
    doc.footnote("Canal fishing permits under the barrage rules do not cover night fishing with nets, which "
                 "remains barred throughout the command area.")
    doc.fact("footnote_exception", S3, "fishing exception", "exception", 3,
             "Canal fishing permits under the barrage rules do not cover night fishing with nets, which "
             "remains barred throughout the command area.",
             stmt="Canal permits do not cover night fishing with nets.",
             emit=False)
    pad(doc, S3, 10)

    # ---- section 4 ----
    S4 = "Climate, soils and forest cover"
    doc.heading(1, S4)
    pad(doc, S4, 10)
    doc.heading(2, "Soils and their crops")
    soil_rows = [
        ["Alluvial loam", "flood plains", "paddy"],
        ["Red sandy loam", "western uplands", "groundnut"],
        ["Laterite gravel", "southern plateaus", "cashew"],
        ["Black regur", "central trough", "cotton"],
        ["Peaty marsh", "eastern bils", "jute"],
        ["Saline flats", "coastal fringe", "salt pans"],
    ]
    doc.table(["Soil class", "Tract where found", "Signature crop"], soil_rows)
    for soil, tract, crop in soil_rows:
        doc.fact("table_cell", S4, "soils table", "table_value", 2,
                 "%s | %s | %s" % (soil, tract, crop),
                 stmt="The tract of %s carries %s and grows %s." % (tract, soil.lower(), crop),
                 emit=False)
    doc.fact("split_distinction", S4, "red soil", "comparison", 2,
             "Red sandy loam of the western uplands drains freely and suits groundnut.",
             stmt="Red sandy loam suits groundnut.")
    pad(doc, S4, 4)
    doc.fact("split_distinction", S4, "laterite contrast", "comparison", 2,
             "Laterite gravel of the southern plateaus, unlike the free draining red soils, sets hard in the "
             "dry months and suits cashew rather than groundnut.",
             stmt="Laterite gravel suits cashew rather than groundnut.",
             conf="G-soils", cluster="CL-soils")
    doc.heading(2, "Monsoon mechanics")
    doc.fact("plain", S4, "monsoon cause", "cause_effect", 1,
             "The summer heating of the central trough draws moist winds inland, and this inflow causes the "
             "burst of the monsoon over Kamarupa in June.",
             stmt="Summer heating draws moist winds inland and causes the June monsoon burst.")
    doc.fact("plain", S4, "rain shadow", "cause_effect", 2,
             "The southern plateaus stand in the rain shadow of the western uplands, so they receive less "
             "than half the rainfall of the plains.",
             stmt="The southern plateaus receive less than half the rainfall of the plains.")
    doc.fact("plain", S4, "forest cover", "number_value", 1,
             "The forest survey records a cover of thirty four percent of the reporting area.",
             stmt="Forest cover is thirty four percent of the reporting area.")
    doc.fact("plain", S4, "variability formula", "formula", 2,
             "Rainfall variability is computed as deviation divided by mean, written v = d / m.",
             stmt="Rainfall variability is deviation divided by mean.")
    pad(doc, S4, 10)

    # ---- section 5 ----
    S5 = "Economy and public finance"
    doc.heading(1, S5)
    pad(doc, S5, 12)
    doc.heading(2, "The annual budget at a glance")
    budget_rows = [
        ["Receipts from taxes", "48200", "61"],
        ["Non tax receipts", "9400", "12"],
        ["Grants and aid", "6300", "8"],
        ["Salaries and pensions", "31500", "40"],
        ["Interest payments", "11800", "15"],
        ["Capital works", "14900", "19"],
        ["Subsidies", "7100", "9"],
        ["Reserve and suspense", "800", "1"],
    ]
    doc.table(["Budget head", "Crore in kam", "Share in percent"], budget_rows)
    for head, amt, sh in budget_rows:
        doc.fact("table_cell", S5, "budget table", "table_value",
                 1 if head in ("Receipts from taxes", "Salaries and pensions") else 2,
                 "%s | %s | %s" % (head, amt, sh),
                 stmt="The budget allots %s crore kam to %s, a share of %s percent." % (amt, head.lower(), sh),
                 emit=False)
    doc.heading(2, "Flagship schemes")
    schemes = [
        ("Green Canopy Mission of 2015", "plant twelve lakh saplings with an outlay of three hundred crore kam"),
        ("River School Boats of 2017", "run forty floating schools with an outlay of ninety crore kam"),
        ("Grain Vault Reform of 2018", "build two hundred rural godowns with an outlay of one hundred and fifty crore kam"),
        ("Weaver Direct Benefit of 2019", "pay nine thousand looms with an outlay of sixty crore kam"),
        ("Hill Road Grid of 2020", "lay six hundred kilometres of road with an outlay of eight hundred crore kam"),
        ("Milk Shed Cooperatives of 2021", "federate three hundred societies with an outlay of forty five crore kam"),
        ("Seed Bank Network of 2022", "stock eighty native varieties with an outlay of twenty crore kam"),
        ("Ferry Modernisation of 2023", "refit twenty five ferries with an outlay of one hundred crore kam"),
    ]
    for name, detail in schemes:
        doc.fact("plain", S5, "schemes", "scheme", 2,
                 "- The %s was launched to %s." % (name, detail),
                 stmt="The %s was launched to %s." % (name, detail), emit=False)
    doc.bullet_list(["The %s was launched to %s." % (n, d) for n, d in schemes])
    doc.fact("buried_paragraph", S5, "per capita", "number_value", 2,
             "Between long passages on market yards, weighbridges and auction halls, the bulletin states the "
             "one comparable figure: per capita income stood at ninety six thousand kam in the reference year.",
             stmt="Per capita income stood at ninety six thousand kam in the reference year.")
    t5a = "The five year plan of 1966 set an outlay of four thousand crore kam."
    t5b = "The plan achieved a growth of three percent against a target of four percent."
    t5c = "Growth is measured as increase divided by base, written g = i / b."
    doc.fact("compound_sentence", S5, "plan outlay", "number_value", 2, t5a, emit=False)
    doc.fact("compound_sentence", S5, "plan result", "number_value", 3, t5b, emit=False)
    doc.fact("compound_sentence", S5, "growth formula", "formula", 2, t5c, emit=False)
    doc.emit_para_facts([t5a, t5b, t5c])
    doc.footnote("Small handlooms with fewer than four looms are exempt from the power duty, which is the "
                 "only exemption in the duty schedule.")
    doc.fact("footnote_exception", S5, "duty exception", "exception", 3,
             "Small handlooms with fewer than four looms are exempt from the power duty, which is the "
             "only exemption in the duty schedule.",
             stmt="Handlooms with fewer than four looms are exempt from power duty.",
             emit=False)
    pad(doc, S5, 14)

    # ---- section 6 ----
    S6 = "Institutions of governance"
    doc.heading(1, S6)
    pad(doc, S6, 11)
    doc.heading(2, "Three commissions compared")
    comm_rows = [
        ["Election Commission", "Article 71", "conduct of polls"],
        ["Service Commission", "Article 72", "recruitment to posts"],
        ["Finance Commission", "Article 73", "sharing of revenues"],
        ["River Board", "Article 74", "adjudication of waters"],
        ["Audit Office", "Article 75", "scrutiny of accounts"],
        ["Language Panel", "Article 76", "recognition of tongues"],
    ]
    doc.table(["Constitutional body", "Founded under", "Core function"], comm_rows)
    for body, art, fn in comm_rows:
        doc.fact("table_cell", S6, "bodies table", "institution",
                 1 if body in ("Election Commission", "Finance Commission") else 2,
                 "%s | %s | %s" % (body, art, fn),
                 stmt="The %s founded under %s handles %s." % (body, art, fn),
                 emit=False)
    doc.fact("confusable_pair", S6, "election vs service", "comparison", 1,
             "The Election Commission conducts polls while the Service Commission recruits to posts, and the "
             "two are often confused because both select people for public roles.",
             stmt="The Election Commission conducts polls while the Service Commission recruits to posts.",
             conf="G-bodies", cluster="CL-bodies")
    doc.fact("confusable_pair", S6, "finance vs audit", "comparison", 2,
             "The Finance Commission shares revenues between tiers whereas the Audit Office scrutinises how "
             "those revenues were spent.",
             stmt="The Finance Commission shares revenues while the Audit Office scrutinises spending.",
             conf="G-bodies", cluster="CL-bodies")
    doc.heading(2, "How a bill becomes law")
    doc.fact("plain", S6, "bill process", "process", 1,
             "A bill passes through introduction, committee scrutiny, two readings, assent, and notification "
             "before it becomes law.",
             stmt="A bill passes introduction, scrutiny, two readings, assent, and notification.")
    doc.bullet_list([
        "Introduction of the bill in either house marks the first step.",
        "Committee scrutiny of clauses marks the second step.",
        "Two readings with debate mark the third step.",
        "Assent of the head of state marks the fourth step.",
        "Notification in the gazette marks the fifth and final step.",
    ])
    doc.fact("plain", S6, "bill classes", "classification", 2,
             "Bills fall into three classes, namely money bills, finance bills, and ordinary bills.",
             stmt="Bills fall into money bills, finance bills, and ordinary bills.")
    doc.footnote("An ordinance lapses if the houses do not approve it within six weeks of reassembly, which "
                 "is the only time bar in the ordinance chapter.")
    doc.fact("footnote_exception", S6, "ordinance exception", "exception", 2,
             "An ordinance lapses if the houses do not approve it within six weeks of reassembly, which "
             "is the only time bar in the ordinance chapter.",
             stmt="An ordinance lapses without approval within six weeks of reassembly.",
             emit=False)
    pad(doc, S6, 10)

    # ---- section 7 (short, dense) ----
    S7 = "Culture, awards and honours"
    doc.heading(1, S7)
    pad(doc, S7, 5)
    awards = [
        ("Sahitya Ratna of 1969", "letters"),
        ("Kala Shree of 1972", "performing arts"),
        ("Vigyan Bhushan of 1975", "science"),
        ("Seva Padma of 1980", "public service"),
        ("Khel Gaurav of 1985", "sports"),
        ("Shilpi Samman of 1990", "crafts"),
        ("Sangeet Mala of 1995", "music"),
    ]
    for name, field in awards:
        doc.fact("long_list_item", S7, "awards", "list_item", 2 if field in ("letters", "science") else 3,
                 "- The %s honours distinction in %s." % (name, field),
                 stmt="The %s honours distinction in %s." % (name, field), emit=False)
    doc.bullet_list(["The %s honours distinction in %s." % (n, f) for n, f in awards])
    doc.fact("confusable_pair", S7, "kala vs sangeet", "comparison", 2,
             "The Kala Shree honours the performing arts while the Sangeet Mala honours music alone, though "
             "both celebrate performance.",
             stmt="The Kala Shree honours performing arts while the Sangeet Mala honours music alone.",
             conf="G-awards", cluster="CL-awards")
    pad(doc, S7, 5)

    # ---- section 8 ----
    S8 = "Profile of Kamarupa state"
    doc.heading(1, S8)
    pad(doc, S8, 11)
    doc.heading(2, "Protected areas")
    park_rows = [
        ["Meyong National Park", "1978", "420"],
        ["Tirung Sanctuary", "1981", "260"],
        ["Saimang Reserve", "1986", "180"],
        ["Nongri Gardens", "1992", "95"],
        ["Diplai Wetland", "2001", "60"],
    ]
    doc.table(["Protected area", "Notified in", "Area in square kilometres"], park_rows)
    for park, yr, area in park_rows:
        doc.fact("table_cell", S8, "parks table", "table_value", 1 if park == "Meyong National Park" else 2,
                 "%s | %s | %s" % (park, yr, area),
                 stmt="The %s notified in %s spans %s square kilometres." % (park, yr, area),
                 emit=False)
    doc.heading(2, "Festivals of the calendar")
    fests = [
        ("Bihu of spring in April", "sowing prayers"),
        ("Bihu of autumn in October", "harvest thanks"),
        ("Boat Race of June", "river homage"),
        ("Lamp Night of November", "ancestral remembrance"),
        ("Seed Drill of July", "monsoon onset"),
        ("Hornbill Week of December", "forest fraternity"),
    ]
    for name, meaning in fests:
        doc.fact("long_list_item", S8, "festivals", "list_item", 3,
                 "- The %s marks %s." % (name, meaning),
                 stmt="The %s marks %s." % (name, meaning), emit=False)
    doc.bullet_list(["The %s marks %s." % (n, m) for n, m in fests])
    doc.fact("repeated_detail", S8, "baruni elaboration", "number_value", 2,
             "Returning to the Baruni barrage of the Sonai, the state profile adds the missing figure: the "
             "barrage diverts one hundred and twenty cusecs through the Baruni canal.",
             stmt="The Baruni barrage diverts one hundred and twenty cusecs through the Baruni canal.")
    doc.fact("distributed_chronology", S8, "charter echo", "date", 2,
             "The state portal recalls that the Charter adopted in 1963 commenced in 1964.",
             stmt="The Charter adopted in 1963 commenced in 1964.")
    doc.fact("repeated_detail", S8, "charter size echo", "number_value", 3,
             "The portal further notes that the original count of two hundred and ninety articles has since "
             "grown past three hundred.",
             stmt="The original count of two hundred and ninety articles has grown past three hundred.")
    doc.footnote("Grazing permits in the wetland buffer do not cover the nesting months of April and May, "
                 "which remain closed to all entry.")
    doc.fact("footnote_exception", S8, "grazing exception", "exception", 3,
             "Grazing permits in the wetland buffer do not cover the nesting months of April and May, "
             "which remain closed to all entry.",
             stmt="Grazing permits do not cover the nesting months of April and May.",
             emit=False)
    pad(doc, S8, 12)
    doc.fact("post_padding", S8, "ferry fleet", "number_value", 2,
             "After the long survey of minor ghats and landing points, the register gives the fleet strength: "
             "twenty five ferries ply the state waterways.",
             stmt="Twenty five ferries ply the state waterways.")
    doc.fact("post_padding", S8, "ghat count", "number_value", 3,
             "The same register counts one hundred and ten recognised landing ghats.",
             stmt="The register counts one hundred and ten recognised landing ghats.")
    doc.fact("post_padding", S8, "night halt", "exception", 2,
             "Night halts are barred at all ghats save Chandrapur and Mornoi, which keep skeletal crews.",
             stmt="Night halts are barred at all ghats save Chandrapur and Mornoi.")
    return [S1, S2, S3, S4, S5, S6, S7, S8]


# ---------------------------------------------------------------- build
DIM_BY_TIER = {
    1: {"importance": "high", "exam_relevance": "high", "factual_density": "high",
        "discrimination_value": "high", "revision_priority": "high"},
    2: {"importance": "high", "exam_relevance": "medium", "factual_density": "medium",
        "discrimination_value": "medium", "revision_priority": "medium"},
    3: {"importance": "medium", "exam_relevance": "low", "factual_density": "medium",
        "discrimination_value": "low", "revision_priority": "low"},
}

COGN = {
    "date": "recall", "article": "recall", "amendment": "recall",
    "number_value": "recall", "table_value": "recall", "list_item": "recall",
    "person": "recall", "place": "recall", "event": "recall",
    "scheme": "understanding", "institution": "understanding",
    "organization": "understanding", "definition": "understanding",
    "term": "understanding", "report": "understanding", "treaty": "understanding",
    "comparison": "distinction", "exception": "distinction",
    "classification": "distinction",
    "cause_effect": "application", "process": "application",
    "formula": "application", "principle": "application",
    "theory": "application", "concept": "understanding",
}

LOW_CONCEPTUAL = {"date", "article", "amendment", "number_value", "table_value",
                  "list_item", "person", "place", "event"}


def build_inventory(doc, struct):
    blocks = struct["blocks"]
    units = []
    for i, f in enumerate(doc.facts):
        hits = [b for b in blocks if f["text"] in (b.get("text") or "")]
        if len(hits) != 1:
            fail("fact %s located in %d blocks (need exactly 1)" % (f["fid"], len(hits)))
        b = hits[0]
        kid = "KU-%04d" % (i + 1)
        f["ku_id"] = kid
        f["block_id"] = b["id"]
        d = dict(DIM_BY_TIER[f["tier"]])
        d["conceptual_density"] = "low" if f["kutype"] in LOW_CONCEPTUAL else "medium"
        if f["kutype"] in ("comparison", "classification", "concept"):
            # keep application forms for genuine mechanisms only; paired
            # comparisons already require recall+distinction+statement
            d["conceptual_density"] = "low"
        paired = bool(f["conf"])
        d["confusion_risk"] = "high" if paired else ("medium" if f["tier"] == 1 else "low")
        if f["tier"] == 1 and f["kutype"] in ("cause_effect", "process", "formula") and not paired:
            # {recall, statement, application} fits per_ku_cap=3
            d["confusion_risk"] = "low"
        d["recall_value"] = "high" if f["tier"] == 1 else "medium"
        d["conceptual_value"] = d["conceptual_density"]
        d["confusion_value"] = d["confusion_risk"]
        d["elimination_value"] = "high" if paired else "medium"
        d["statement_potential"] = "high" if f["tier"] == 1 else ("medium" if f["tier"] == 2 else "low")
        units.append({
            "id": kid, "topic": f["section"].split(" of ")[0].title(),
            "subtopic": f["subtopic"], "type": f["kutype"],
            "statement": f["stmt"], "supporting_excerpt": f["text"],
            "source": {"page": b["page"], "section_path": b["section_path"],
                       "block_id": b["id"], "char_start": 0, "char_end": 0,
                       "table_ref": None},
            "origin": "source", "tier": f["tier"], "tier_history": [],
            "dimensions": d, "related_ku": list(f["related"]),
            "confusable_with": [], "omission_reason": None, "language": "en",
            "cognitive_level": f["cogn"] or COGN.get(f["kutype"], "recall"),
            "confusion_cluster": f["cluster"], "prerequisite_units": [],
        })
    groups = {}
    for f in doc.facts:
        if f["conf"]:
            groups.setdefault(f["conf"], []).append(f["ku_id"])
    kui = {u["id"]: u for u in units}
    for f in doc.facts:
        if f["conf"]:
            f["cluster"] = f["cluster"] or f["conf"].replace("G-", "CL-")
            peers = [k for k in groups[f["conf"]] if k != f["ku_id"]]
            kui[f["ku_id"]]["confusable_with"] = peers
            kui[f["ku_id"]]["related_ku"] = list(set(kui[f["ku_id"]]["related_ku"]) | set(peers))
            kui[f["ku_id"]]["confusion_cluster"] = f["cluster"]
    return {"units": units}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ensure_dir(a.out)
    doc = Doc()
    sections = build_sections(doc)
    src = doc.text()
    src_path = os.path.join(a.out, "longdoc_source.md")
    with open(src_path, "w", encoding="utf-8") as fh:
        fh.write(src)
    print("source: %d chars, %d facts" % (len(src), len(doc.facts)))
    import ingest as ingest_mod
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="longdoc_struct_")
    rc = ingest_mod.main([src_path, "--out", tmpd, "--run-id", "s"])
    if rc:
        fail("ingest failed on generated source")
    struct = load_json(os.path.join(tmpd, "s", "document_structure.json"))
    print("ingest: %d blocks, %d pages, status=%s limitations=%s" % (
        len(struct["blocks"]),
        max(b["page"] for b in struct["blocks"]),
        struct["extraction_status"], struct["limitations"]))
    from lib_common import norm
    ku_texts = [norm(f["stmt"] + " " + f["text"]) for f in doc.facts]
    header_vals = {norm(c) for h in doc.headers for c in h}
    unexplained = []
    ignored = []
    for an in anchors_mod.extract(struct["blocks"]):
        v = norm(an.get("value", ""))
        if not v:
            continue
        if any(v and v in t for t in ku_texts):
            continue
        if an.get("kind") == "table_cell" and v in header_vals:
            ignored.append({"anchor_id": an["id"], "reason": "table_header",
                            "value": an["value"]})
            continue
        if an.get("kind") == "list_marker":
            ignored.append({"anchor_id": an["id"], "reason": "formatting_artifact",
                            "value": an["value"]})
            continue
        unexplained.append(an)
    if unexplained:
        for an in unexplained[:25]:
            print("UNEXPLAINED ANCHOR %s [%s] in %s: %r" % (
                an["id"], an["kind"], an["block_id"], an["value"][:80]))
        fail("%d anchors not covered by any KU and not ignorable" % len(unexplained))
    print("anchors: %d ignored (header/marker), 0 unexplained" % len(ignored))
    save_json(os.path.join(a.out, "ignored_anchors.json"), ignored)
    inv = build_inventory(doc, struct)
    save_json(os.path.join(a.out, "inventory.json"), inv)
    manifest = [{"fact_id": f["fid"], "ku_id": f["ku_id"], "trap": f["trap"],
                 "section": f["section"], "excerpt": f["text"],
                 "ku_type": f["kutype"], "tier": f["tier"],
                 "block_id": f["block_id"]} for f in doc.facts]
    save_json(os.path.join(a.out, "manifest.json"), manifest)
    drop_traps = {"table_cell", "long_list_item", "footnote_exception",
                  "buried_paragraph", "compound_sentence"}
    dropped = [f for f in doc.facts if f["trap"] in drop_traps][:5]
    drop_ids = {f["ku_id"] for f in dropped}
    first = {"units": [u for u in inv["units"] if u["id"] not in drop_ids]}
    save_json(os.path.join(a.out, "inventory_firstpass.json"), first)
    diffs = [{"ku_id": f["ku_id"], "action": "added", "status": "resolved",
              "detail": "Second pass over %s found trap fact (%s) with no KU; added %s."
                        % (f["section"], f["trap"], f["ku_id"])} for f in dropped]
    diffs += [
        {"action": "rejected", "status": "resolved",
         "detail": "Candidate KU on the bridge prose is low-value commentary, not examinable."},
        {"action": "rejected", "status": "resolved",
         "detail": "Candidate KU duplicating a charter-date KU merged; no separate unit needed."},
        {"action": "rejected", "status": "resolved",
         "detail": "Relative phrase in padding is not a precise fact; covered numerically elsewhere."},
    ]
    save_json(os.path.join(a.out, "inventory_diff.json"),
              {"pass": 2, "status": "resolved", "diffs": diffs})
    print("inventory: %d units (%d first-pass, 5 via second pass)" % (len(inv["units"]), len(first["units"])))
    print("sections: %d" % len(sections))
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))
