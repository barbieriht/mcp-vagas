// Currículo de uma coluna, amigável a ATS: texto selecionável, sem hifenização nem ligaduras.
// Os dados chegam como JSON em sys.inputs.data; strings são inseridas como texto literal.

#let data = json(bytes(sys.inputs.data))
#let b = data.basics

#let get(d, key) = d.at(key, default: none)
#let opt(x) = if x == none { [] } else { x }
#let url(s) = if s.starts-with("http") { s } else { "https://" + s }
#let span(d) = {
  let parts = (get(d, "start"), get(d, "end")).filter(x => x != none)
  if parts.len() == 0 { none } else { parts.map(str).join(" – ") }
}

#set document(title: b.name + " - Resume", author: b.name)
#set page(paper: "a4", margin: (x: 1.6cm, y: 1.4cm))
#set text(font: "Libertinus Serif", size: 10.5pt, lang: "en", ligatures: false, hyphenate: false)
#set par(justify: false, leading: 0.55em, spacing: 0.7em)
#set list(indent: 0.6em, spacing: 0.5em)

#let section(title) = block(
  width: 100%, above: 1.1em, below: 0.6em, inset: (bottom: 2pt), stroke: (bottom: 0.5pt),
  text(size: 11.5pt, weight: "bold", title),
)

#let head(title, right, subtitle: none, right2: none) = {
  [#text(weight: "bold", title) #h(1fr) #opt(right)]
  if subtitle != none or right2 != none {
    linebreak()
    [#emph(opt(subtitle)) #h(1fr) #opt(right2)]
  }
}

#let paragraphs(item) = {
  for p in item.at("paragraphs", default: ()) {
    if "bullets" in p { list(..p.bullets) } else { par(p.text) }
  }
}

#let contacts = {
  let items = ()
  if get(b, "phone") != none { items.push(b.phone) }
  if get(b, "email") != none { items.push(link("mailto:" + b.email, b.email)) }
  if get(b, "location") != none { items.push(b.location) }
  for l in b.at("links", default: ()) { items.push(link(url(l), l)) }
  items
}

#align(center)[
  #text(size: 17pt, weight: "bold", b.name)
  #if get(b, "headline") != none { linebreak(); b.headline }
  #if contacts.len() > 0 { linebreak(); contacts.join(" | ") }
]

#if get(data, "summary") != none {
  section("Summary")
  par(data.summary)
}

#let render-education(education) = {
  section("Education")
  for e in education {
    let subtitle = (e.degree, get(e, "field")).filter(x => x != none).join(", ")
    block(above: 0.85em, breakable: false, head(e.institution, span(e), subtitle: subtitle))
    if get(e, "notes") != none { par(e.notes) }
  }
}

#let render-experience(experience) = {
  section("Experience")
  for (i, x) in experience.enumerate() {
    if i > 0 { v(0.4em) }
    let title = if get(x, "context") != none { x.company + " – " + x.context } else { x.company }
    block(above: 0.85em, breakable: false, head(title, span(x), subtitle: x.title, right2: get(x, "location")))
    paragraphs(x)
  }
}

#let render-projects(projects) = {
  section("Projects")
  for p in projects {
    let name = if get(p, "link") != none { link(url(p.link), p.name) } else { p.name }
    block(above: 0.85em, breakable: false, head(name, span(p)))
    paragraphs(p)
  }
}

#let render-publications(publications) = {
  section("Publications")
  list(..publications.map(p => {
    let title = if get(p, "link") != none { link(url(p.link), p.title) } else { p.title }
    let details = (get(p, "authors"), get(p, "venue"), get(p, "year")).filter(x => x != none).map(str)
    [#text(weight: "bold", title)#if details.len() > 0 [. #details.join(", ").]]
  }))
}

#let render-skills(skills) = {
  section("Technical Skills")
  for g in skills { par[#text(weight: "bold", g.label + ":") #g.terms.join(", ")] }
}

#let render-certifications(certifications) = {
  section("Certifications")
  for g in certifications {
    let items = g.items.map(c => {
      let tail = (get(c, "provider"), get(c, "year")).filter(x => x != none).map(str)
      if tail.len() > 0 { c.name + " – " + tail.join(" (") + if tail.len() > 1 { ")" } else { "" } } else { c.name }
    })
    par[#text(weight: "bold", g.label + ":") #items.join("; ")]
  }
}

#let render-languages(languages) = {
  section("Languages")
  for l in languages {
    par[#text(weight: "bold", l.name + ":") #l.level#if get(l, "note") != none [ – #l.note]]
  }
}

#let renderers = (
  education: render-education,
  experience: render-experience,
  projects: render-projects,
  publications: render-publications,
  skills: render-skills,
  certifications: render-certifications,
  languages: render-languages,
)
#let order = data.at("order", default: (
  "education", "experience", "projects", "publications", "skills", "certifications", "languages",
))
#for name in order {
  let items = data.at(name, default: ())
  if items.len() > 0 { renderers.at(name)(items) }
}
