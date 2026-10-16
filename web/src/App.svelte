<script lang="ts">
  import type { Job, Pocket } from './lib/api'
  import JobForm from './lib/JobForm.svelte'
  import JobStatus from './lib/JobStatus.svelte'
  import PocketTable from './lib/PocketTable.svelte'
  import StructureViewer from './lib/StructureViewer.svelte'

  const fromHash = () => {
    const match = location.hash.match(/^#job=(\d+)$/)
    return match ? Number(match[1]) : null
  }

  let jobId = $state<number | null>(fromHash())
  let job = $state<Job | null>(null)
  let selected = $state<Pocket | null>(null)

  const hasResults = $derived(job?.proteins.some((p) => p.status === 'succeeded') ?? false)

  function open(id: number) {
    location.hash = `job=${id}`
  }
</script>

<svelte:window
  onhashchange={() => {
    jobId = fromHash()
    job = null
    selected = null
  }}
/>

<main>
  <h1>pocketscan</h1>
  <JobForm onsubmitted={open} />

  {#if jobId !== null}
    {#key jobId}
      <JobStatus {jobId} onchange={(j) => (job = j)} />
      {#if hasResults}
        <PocketTable {jobId} onselect={(p) => (selected = p)} />
        <StructureViewer {jobId} pocket={selected} />
      {/if}
    {/key}
  {/if}
</main>
