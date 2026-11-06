import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  addPapers,
  createEvidenceTopic,
  deleteEvidenceTopic,
  fetchEvidence,
  fetchEvidenceStatus,
  fetchEvidenceTopics,
  saveEvidence,
  searchPubMed,
  setDisputedBy,
  setEvidenceStatus,
  startEvidenceFetch,
  startTakeawayRewrite,
  updateEvidenceTopic,
  type EvidenceEntry,
  type EvidenceFields,
  type EvidenceTopic,
  type EvidenceTopicInput,
  type PubMedHit,
} from '../api'
import { Card } from '../components/Card'
import { number, sentence, shortDate } from '../format'

const DESIGNS = [
  'meta_analysis',
  'systematic_review',
  'randomized_trial',
  'controlled_trial',
  'observational',
  'narrative_review',
  'other',
]
const EFFECTS = ['positive', 'negative', 'no_effect', 'mixed', 'unclear']
const TEXT_FIELDS = ['claim', 'population', 'intervention', 'outcome', 'takeaway', 'limitations'] as const
const INPUT =
  'w-full min-w-0 rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary focus:border-accent focus:outline-none sm:text-sm'

type Tab = 'queue' | 'library' | 'find' | 'skipped' | 'topics'

const SEARCH_SIZES = [10, 20, 50, 100]

const STATUS_LABELS: Record<EvidenceEntry['status'], string> = {
  pending: 'To review',
  approved: 'In the library',
  rejected: 'Rejected',
  skipped: 'Not relevant',
}

function paperUrl(entry: EvidenceEntry): string {
  return entry.doi ? `https://doi.org/${entry.doi}` : `https://pubmed.ncbi.nlm.nih.gov/${entry.pmid}/`
}

function useRefreshEvidence() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all(
      ['evidence', 'evidence-topics', 'pubmed'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    )
}

function FetchBar() {
  const refresh = useRefreshEvidence()
  const status = useQuery({
    queryKey: ['evidence-fetch'],
    queryFn: fetchEvidenceStatus,
    refetchInterval: (query) => (query.state.data?.running ? 3000 : false),
  })
  const start = useMutation({ mutationFn: startEvidenceFetch, onSuccess: () => void status.refetch() })
  const rewrite = useMutation({ mutationFn: startTakeawayRewrite, onSuccess: () => void status.refetch() })
  const running = status.data?.running ?? false
  const rewriting = running && status.data?.task === 'rewrite'
  const last = status.data?.last
  const wasRunning = useRef(running)
  useEffect(() => {
    if (wasRunning.current && !running) void refresh()
    wasRunning.current = running
  }, [running, refresh])
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
      <button
        type="button"
        onClick={() => start.mutate()}
        disabled={running || status.data?.available === false}
        className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised disabled:opacity-50"
      >
        {running && !rewriting ? (status.data?.task === 'add' ? 'Adding papers…' : 'Fetching papers…') : 'Fetch now'}
      </button>
      <button
        type="button"
        onClick={() => {
          if (confirm('Write new takeaways for every paper? This replaces takeaways you have edited.')) rewrite.mutate()
        }}
        disabled={running || status.data?.available === false}
        className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised disabled:opacity-50"
      >
        {rewriting ? 'Rewriting takeaways…' : 'Rewrite takeaways'}
      </button>
      {status.data?.available === false && <span>Fetching needs ANTHROPIC_API_KEY for the summaries.</span>}
      {last && !running && (
        <span>
          Last fetch {new Date(last.started_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })},{' '}
          {last.added} new {last.added === 1 ? 'paper' : 'papers'}
        </span>
      )}
      {last && !running && last.errors.length > 0 && (
        <span className="text-warning" title={last.errors.join('\n')}>
          ▲ {last.errors.length} {last.errors.length === 1 ? 'problem' : 'problems'}: {last.errors[0]}
        </span>
      )}
      {start.error && <span className="text-critical">{start.error.message}</span>}
      {rewrite.error && <span className="text-critical">{rewrite.error.message}</span>}
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="text-sm">
      <span className="text-xs text-muted">{label}</span>
      <div className="text-secondary">{children}</div>
    </div>
  )
}

function EntryEditor({ entry, onDone }: { entry: EvidenceEntry; onDone: () => void }) {
  const refresh = useRefreshEvidence()
  const [fields, setFields] = useState<EvidenceFields>({
    claim: entry.claim,
    population: entry.population,
    intervention: entry.intervention,
    outcome: entry.outcome,
    design: entry.design,
    sample_size: entry.sample_size,
    effect: entry.effect,
    takeaway: entry.takeaway,
    limitations: entry.limitations,
    notes: entry.notes,
  })
  const save = useMutation({
    mutationFn: () => saveEvidence(entry.id, fields),
    onSuccess: async () => {
      await refresh()
      onDone()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      {TEXT_FIELDS.map((name) => (
        <label key={name} className="block text-xs text-muted sm:col-span-2">
          {sentence(name)}
          <textarea
            rows={2}
            className={INPUT}
            value={fields[name]}
            onChange={(e) => setFields({ ...fields, [name]: e.target.value })}
          />
        </label>
      ))}
      <label className="block text-xs text-muted">
        Design
        <select className={INPUT} value={fields.design} onChange={(e) => setFields({ ...fields, design: e.target.value })}>
          {DESIGNS.map((design) => (
            <option key={design} value={design}>
              {sentence(design)}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs text-muted">
        Effect
        <select className={INPUT} value={fields.effect} onChange={(e) => setFields({ ...fields, effect: e.target.value })}>
          {EFFECTS.map((effect) => (
            <option key={effect} value={effect}>
              {sentence(effect)}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs text-muted">
        Sample size
        <input
          type="number"
          className={INPUT}
          value={fields.sample_size ?? ''}
          onChange={(e) => setFields({ ...fields, sample_size: e.target.value ? Number(e.target.value) : null })}
        />
      </label>
      <label className="block text-xs text-muted sm:col-span-2">
        Your notes, the coach sees them
        <textarea
          rows={2}
          className={INPUT}
          value={fields.notes ?? ''}
          onChange={(e) => setFields({ ...fields, notes: e.target.value || null })}
        />
      </label>
      <div className="flex gap-2 sm:col-span-2">
        <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white">
          Save
        </button>
        <button type="button" onClick={onDone} className="rounded-lg border border-line px-3 py-1.5 text-sm text-secondary">
          Cancel
        </button>
        {save.error && <span className="text-xs text-critical">{save.error.message}</span>}
      </div>
    </form>
  )
}

function EntryCard({ entry, library }: { entry: EvidenceEntry; library: EvidenceEntry[] }) {
  const refresh = useRefreshEvidence()
  const [editing, setEditing] = useState(false)
  const status = useMutation({
    mutationFn: (next: EvidenceEntry['status']) => setEvidenceStatus(entry.id, next),
    onSuccess: refresh,
  })
  const dispute = useMutation({
    mutationFn: (by: number | null) => setDisputedBy(entry.id, by),
    onSuccess: refresh,
  })
  const disputedBy = library.find((other) => other.id === entry.disputed_by_id)
  const button = 'rounded-lg border border-line px-3 py-1.5 text-sm text-secondary hover:bg-raised disabled:opacity-50'
  const saving = status.isPending
  return (
    <section className="min-w-0 rounded-xl border border-line bg-surface p-4">
      <a href={paperUrl(entry)} target="_blank" rel="noreferrer" className="text-sm font-semibold text-primary hover:underline">
        {entry.title}
      </a>
      <p className="mt-0.5 text-xs text-muted">
        {entry.citation}. Grade {entry.grade}, {sentence(entry.design)}
        {entry.sample_size ? `, n = ${number(entry.sample_size)}` : ''}, effect {sentence(entry.effect).toLowerCase()}
      </p>
      {disputedBy && (
        <p className="mt-1 text-xs text-warning">▲ Disputed by {disputedBy.citation}</p>
      )}
      <div className="mt-3">
        {editing ? (
          <EntryEditor entry={entry} onDone={() => setEditing(false)} />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Field label="Claim">{entry.claim}</Field>
            </div>
            <Field label="Population">{entry.population}</Field>
            <Field label="Intervention">{entry.intervention}</Field>
            <Field label="Outcome">{entry.outcome}</Field>
            <Field label="Limitations">{entry.limitations}</Field>
            <div className="sm:col-span-2">
              <Field label="Takeaway">
                <span className="text-primary">{entry.takeaway}</span>
              </Field>
            </div>
            {entry.notes && (
              <div className="sm:col-span-2">
                <Field label="Your notes">{entry.notes}</Field>
              </div>
            )}
            <details className="text-xs text-muted sm:col-span-2">
              <summary className="cursor-pointer select-none">Abstract</summary>
              <p className="mt-1 whitespace-pre-wrap text-secondary">{entry.abstract}</p>
            </details>
          </div>
        )}
      </div>
      {!editing && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {entry.status === 'pending' && (
            <button
              type="button"
              onClick={() => status.mutate('approved')}
              disabled={saving}
              className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              Approve
            </button>
          )}
          <button type="button" onClick={() => setEditing(true)} className={button}>
            Edit
          </button>
          {entry.status === 'pending' && (
            <button
              type="button"
              onClick={() => status.mutate('skipped')}
              disabled={saving}
              title="Read it, not useful for you. The coach will not cite it and it will not be fetched again."
              className={button}
            >
              Not relevant
            </button>
          )}
          {(entry.status === 'approved' || entry.status === 'skipped') && (
            <button type="button" onClick={() => status.mutate('pending')} disabled={saving} className={button}>
              Back to review
            </button>
          )}
          {entry.status !== 'skipped' && (
            <button
              type="button"
              onClick={() => status.mutate('rejected')}
              disabled={saving}
              title="The study is weak or wrong. The coach will not cite it."
              className={button}
            >
              Reject
            </button>
          )}
          {entry.status === 'approved' && library.length > 1 && (
            <label className="flex items-center gap-2 text-xs text-muted">
              Disputed by
              <select
                value={entry.disputed_by_id ?? ''}
                onChange={(e) => dispute.mutate(e.target.value ? Number(e.target.value) : null)}
                className="max-w-48 rounded-lg border border-line bg-page px-2 py-1 text-xs text-primary"
              >
                <option value="">Nothing</option>
                {library
                  .filter((other) => other.id !== entry.id)
                  .map((other) => (
                    <option key={other.id} value={other.id}>
                      {other.citation}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {saving && <span className="text-xs text-muted">Saving…</span>}
          {status.error && <span className="text-xs text-critical">{status.error.message}</span>}
        </div>
      )}
    </section>
  )
}

function EntryList({
  status,
  empty,
  library,
}: {
  status: EvidenceEntry['status']
  empty: string
  library: EvidenceEntry[]
}) {
  const entries = useQuery({ queryKey: ['evidence', status], queryFn: () => fetchEvidence(status) })
  if (entries.isPending) return <p className="text-sm text-muted">Loading…</p>
  if (entries.data?.length === 0) return <p className="text-sm text-muted">{empty}</p>
  return (
    <div className="space-y-4">
      {entries.data?.map((entry) => (
        <EntryCard key={entry.id} entry={entry} library={library} />
      ))}
    </div>
  )
}

function Library({ library }: { library: EvidenceEntry[] }) {
  const [query, setQuery] = useState('')
  const found = useQuery({
    queryKey: ['evidence', 'approved', query],
    queryFn: () => fetchEvidence('approved', query),
    enabled: query.trim().length > 2,
  })
  const shown = query.trim().length > 2 ? (found.data ?? []) : library
  return (
    <div className="space-y-4">
      <label className="block text-xs text-muted">
        Search the approved papers the coach can cite
        <input className={INPUT} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="for example downhill strength" />
      </label>
      {shown.length === 0 && <p className="text-sm text-muted">No approved papers match.</p>}
      {shown.map((entry) => (
        <EntryCard key={entry.id} entry={entry} library={library} />
      ))}
    </div>
  )
}

function hitCitation(hit: PubMedHit): string {
  const who = hit.authors.length > 1 ? `${hit.authors[0]} et al.` : (hit.authors[0] ?? 'Unknown')
  const types = hit.publication_types.filter((type) => type !== 'Journal Article').join(', ')
  return `${who} (${hit.year ?? 'n.d.'}), ${hit.journal ?? 'no journal'}${types ? `. ${types}` : ''}`
}

function SearchHit({ hit, chosen, onToggle }: { hit: PubMedHit; chosen: boolean; onToggle: () => void }) {
  return (
    <section className="flex min-w-0 gap-3 rounded-xl border border-line bg-surface p-4">
      <input
        type="checkbox"
        aria-label={`Add ${hit.title}`}
        checked={chosen}
        disabled={hit.status !== null}
        onChange={onToggle}
        className="mt-1 shrink-0"
      />
      <div className="min-w-0">
        <a
          href={`https://pubmed.ncbi.nlm.nih.gov/${hit.pmid}/`}
          target="_blank"
          rel="noreferrer"
          className="text-sm font-semibold text-primary hover:underline"
        >
          {hit.title}
        </a>
        <p className="mt-0.5 text-xs text-muted">
          {hitCitation(hit)}
          {hit.status && <span className="text-accent">. {STATUS_LABELS[hit.status]}</span>}
        </p>
        <details className="mt-2 text-xs text-muted">
          <summary className="cursor-pointer select-none">Abstract</summary>
          <p className="mt-1 whitespace-pre-wrap text-secondary">{hit.abstract}</p>
        </details>
      </div>
    </section>
  )
}

function FindPapers() {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [size, setSize] = useState(20)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const hits = useQuery({
    queryKey: ['pubmed', query, size],
    queryFn: () => searchPubMed(query, size),
    enabled: query.length > 2,
  })
  const fetchStatus = useQuery({ queryKey: ['evidence-fetch'], queryFn: fetchEvidenceStatus })
  const add = useMutation({
    mutationFn: () => addPapers([...chosen]),
    onSuccess: async () => {
      setChosen(new Set())
      await queryClient.invalidateQueries({ queryKey: ['evidence-fetch'] })
    },
  })
  const toggle = (pmid: string) => {
    const next = new Set(chosen)
    if (next.has(pmid)) next.delete(pmid)
    else next.add(pmid)
    setChosen(next)
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setQuery(draft.trim())
    setChosen(new Set())
    add.reset()
  }
  const running = fetchStatus.data?.running ?? false
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex items-end gap-2">
        <label className="block min-w-0 flex-1 text-xs text-muted">
          Search PubMed for reviews, trials and meta-analyses from any year. Papers with every word in the title come
          first. PubMed syntax such as [tiab] or OR works too.
          <input
            className={INPUT}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="for example downhill training"
          />
        </label>
        <label className="block shrink-0 text-xs text-muted">
          Papers
          <select className={INPUT} value={size} onChange={(e) => setSize(Number(e.target.value))}>
            {SEARCH_SIZES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={draft.trim().length < 3}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
        >
          Search
        </button>
      </form>
      {hits.isFetching && <p className="text-sm text-muted">Searching PubMed…</p>}
      {hits.error && <p className="text-sm text-critical">{hits.error.message}</p>}
      {hits.data?.length === 0 && <p className="text-sm text-muted">PubMed found no matching studies.</p>}
      {hits.data && hits.data.length > 0 && (
        <>
          <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 bg-page py-2 text-xs text-muted">
            <button
              type="button"
              onClick={() => add.mutate()}
              disabled={chosen.size === 0 || running || add.isPending}
              className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
            >
              Add {chosen.size} {chosen.size === 1 ? 'paper' : 'papers'} to review
            </button>
            <span>Tick the papers worth reading. The coach summarizes each one for less than a cent.</span>
            {add.isSuccess && <span className="text-accent">The papers appear under To review when the summaries are done.</span>}
            {add.error && <span className="text-critical">{add.error.message}</span>}
          </div>
          {hits.data.map((hit) => (
            <SearchHit key={hit.pmid} hit={hit} chosen={chosen.has(hit.pmid)} onToggle={() => toggle(hit.pmid)} />
          ))}
        </>
      )}
    </div>
  )
}

function TopicForm({
  initial,
  onSave,
  onDelete,
  topic,
}: {
  initial: EvidenceTopicInput
  onSave: (topic: EvidenceTopicInput) => void
  onDelete?: () => void
  topic?: EvidenceTopic
}) {
  const [values, setValues] = useState(initial)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSave(values)
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_8rem]">
      <label className="block text-xs text-muted">
        Name
        <input required className={INPUT} value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} />
      </label>
      <label className="block text-xs text-muted">
        Papers a week
        <input
          type="number"
          min={0}
          max={20}
          className={INPUT}
          value={values.weekly_limit}
          onChange={(e) => setValues({ ...values, weekly_limit: Number(e.target.value) })}
        />
      </label>
      <label className="block text-xs text-muted sm:col-span-2">
        PubMed search. Reviews, trials and meta-analyses from the last 5 years with an English abstract are added
        automatically.
        <textarea
          required
          rows={3}
          className={`${INPUT} font-mono text-xs`}
          value={values.query}
          onChange={(e) => setValues({ ...values, query: e.target.value })}
        />
      </label>
      <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
        <label className="flex items-center gap-2 text-sm text-secondary">
          <input type="checkbox" checked={values.active} onChange={(e) => setValues({ ...values, active: e.target.checked })} />
          Fetch weekly
        </label>
        <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white">
          Save
        </button>
        {onDelete && (
          <button
            type="button"
            onClick={() => window.confirm(`Delete the topic ${values.name}?`) && onDelete()}
            className="text-xs text-muted hover:text-critical"
          >
            Delete
          </button>
        )}
        {topic && (
          <span className="text-xs text-muted">
            {topic.approved} approved, {topic.pending} to review
            {topic.last_fetched_at ? `, last fetched ${shortDate(topic.last_fetched_at)}` : ', not fetched yet'}
          </span>
        )}
      </div>
    </form>
  )
}

function Topics() {
  const refresh = useRefreshEvidence()
  const topics = useQuery({ queryKey: ['evidence-topics'], queryFn: fetchEvidenceTopics })
  const [adding, setAdding] = useState(false)
  const create = useMutation({ mutationFn: createEvidenceTopic, onSuccess: refresh })
  const update = useMutation({
    mutationFn: ({ id, topic }: { id: number; topic: EvidenceTopicInput }) => updateEvidenceTopic(id, topic),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: deleteEvidenceTopic, onSuccess: refresh })
  const total = topics.data?.filter((t) => t.active).reduce((sum, t) => sum + t.weekly_limit, 0) ?? 0
  return (
    <div className="space-y-4">
      <p className="text-sm text-secondary">Up to {total} new papers a week across the active topics.</p>
      {topics.data?.map((topic) => (
        <Card key={topic.id} title={topic.name}>
          <TopicForm
            topic={topic}
            initial={topic}
            onSave={(input) => update.mutate({ id: topic.id, topic: input })}
            onDelete={() => remove.mutate(topic.id)}
          />
        </Card>
      ))}
      {adding ? (
        <Card title="New topic">
          <TopicForm
            initial={{ name: '', query: '', weekly_limit: 2, active: true }}
            onSave={(topic) => {
              create.mutate(topic)
              setAdding(false)
            }}
          />
        </Card>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised"
        >
          Add topic
        </button>
      )}
    </div>
  )
}

export function ResearchPage() {
  const [tab, setTab] = useState<Tab>('queue')
  const pending = useQuery({ queryKey: ['evidence', 'pending'], queryFn: () => fetchEvidence('pending') })
  const library = useQuery({ queryKey: ['evidence', 'approved'], queryFn: () => fetchEvidence('approved') })
  const tabs: { key: Tab; label: string }[] = [
    { key: 'queue', label: `To review (${pending.data?.length ?? 0})` },
    { key: 'library', label: `Library (${library.data?.length ?? 0})` },
    { key: 'find', label: 'Find papers' },
    { key: 'skipped', label: 'Not relevant' },
    { key: 'topics', label: 'Topics' },
  ]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="tablist">
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              tab === key ? 'border-accent bg-raised font-semibold text-primary' : 'border-line text-secondary hover:bg-raised'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">
        The library is shared by every profile. A paper anyone approves reaches every coach, with the notes on it.
      </p>
      <FetchBar />
      {tab === 'queue' && (
        <EntryList
          status="pending"
          empty="Nothing to review. New papers arrive with the weekly fetch, or find some yourself."
          library={library.data ?? []}
        />
      )}
      {tab === 'skipped' && (
        <EntryList status="skipped" empty="No papers marked as not relevant." library={library.data ?? []} />
      )}
      {tab === 'find' && <FindPapers />}
      {tab === 'library' && <Library library={library.data ?? []} />}
      {tab === 'topics' && <Topics />}
    </div>
  )
}
