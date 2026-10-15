<script lang="ts">
  import { getPockets, type Pocket, type PocketSort } from './api'

  let { jobId, onselect }: { jobId: number; onselect?: (pocket: Pocket) => void } = $props()

  const pageSize = 20

  let items = $state<Pocket[]>([])
  let total = $state(0)
  let error = $state<string | null>(null)
  let loading = $state(false)

  let sort = $state<PocketSort>('score')
  let order = $state<'asc' | 'desc'>('desc')
  let accession = $state('')
  let minScore = $state<number | null>(null)
  let offset = $state(0)

    let latest = 0

  async function load() {
    const request = ++latest
    loading = true
    try {
      const page = await getPockets(jobId, {
        sort,
        order,
        accession: accession.trim() || undefined,
        min_score: minScore ?? undefined,
        limit: pageSize,
        offset,
      })
      if (request !== latest) return // a newer request has been sent; ignore this answer
      items = page.items
      total = page.total
      error = null
    } catch (e) {
      if (request !== latest) return
      error = e instanceof Error ? e.message : String(e)
    } finally {
      if (request === latest) loading = false
    }
  }

  $effect(() => {
    load()
  })

  function sortBy(column: PocketSort) {
    if (sort === column) {
      order = order === 'asc' ? 'desc' : 'asc'
    } else {
      sort = column
      order = column === 'rank' ? 'asc' : 'desc'
    }
    offset = 0
  }

  const from = $derived(total === 0 ? 0 : offset + 1)
  const to = $derived(offset + items.length)

  const fmt = (value: number | null, digits = 1) => (value === null ? '—' : value.toFixed(digits))

</script>

<section>
  <div class="filters">
    <label>
      Accession
      <input bind:value={accession} oninput={() => (offset = 0)} placeholder="e.g. P08100" />
    </label>
    <label>
      Min score
      <input type="number" step="0.01" bind:value={minScore} oninput={() => (offset = 0)} />
    </label>
  </div>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  <table class:loading>
    <thead>
      <tr>
        <th>Accession</th>
        {#each [['rank', 'Rank'], ['score', 'Score'], ['volume_a3', 'Volume (Å³)'], ['mean_sasa_a2', 'Mean SASA (Å²)'], ['mean_plddt', 'Mean pLDDT']] as [column, label]}
          <th>
            <button type="button" onclick={() => sortBy(column as PocketSort)}>
              {label}{sort === column ? (order === 'asc' ? ' ▲' : ' ▼') : ''}
            </button>
          </th>
        {/each}
        <th>Residues</th>
      </tr>
    </thead>
    <tbody>
      {#each items as pocket (pocket.accession + ':' + pocket.rank)}
        <tr>
          <td>{pocket.accession}</td>
          <td><button type="button" onclick={() => onselect?.(pocket)}>#{pocket.rank}</button></td>
          <td>{fmt(pocket.score, 3)}</td>
          <td>{fmt(pocket.volume_a3)}</td>
          <td>{fmt(pocket.mean_sasa_a2)}</td>
          <td>{fmt(pocket.mean_plddt)}</td>
          <td>{pocket.residues.length}</td>
        </tr>
      {:else}
        <tr><td colspan="7">{loading ? 'Loading…' : 'No pockets match.'}</td></tr>
      {/each}
    </tbody>
  </table>

  <div class="pager">
    <button type="button" disabled={offset === 0} onclick={() => (offset = Math.max(0, offset - pageSize))}>
      ← Prev
    </button>
    <span>{from}–{to} of {total}</span>
    <button type="button" disabled={to >= total} onclick={() => (offset += pageSize)}>Next →</button>
  </div>
</section>

<style>
  table { border-collapse: collapse; width: 100%; }
  th, td { padding: 0.35rem 0.6rem; text-align: left; border-bottom: 1px solid #8884; }
  th button { all: unset; cursor: pointer; font-weight: 600; }
  table.loading { opacity: 0.6; }
  .filters { display: flex; gap: 1rem; margin-bottom: 1rem; }
  .pager { display: flex; gap: 1rem; align-items: center; justify-content: flex-end; margin-top: 0.75rem; }
  .error { color: #c33; }
</style>

