<script lang="ts">
  import type { Job } from './lib/api'
  import JobForm from './lib/JobForm.svelte'
  import JobStatus from './lib/JobStatus.svelte'
  import PocketTable from './lib/PocketTable.svelte'

  const fromHash = () => {
    const match = location.hash.match(/^#job=(\d+)$/)
    return match ? Number(match[1]) : null
  }

  let jobId = $state<number | null>(fromHash())
  let job = $state<Job | null>(null)

  const hasResults = $derived(job?.proteins.some((p) => p.status === 'succeeded') ?? false)

  function open(id: number) {
    location.hash = `job=${id}`
  }
</script>

<svelte:window
  onhashchange={() => {
    jobId = fromHash()
    job = null
  }}
/>

<main>
  <h1>pocketscan</h1>
  <JobForm onsubmitted={open} />

  {#if jobId !== null}
    {#key jobId}
      <JobStatus {jobId} onchange={(j) => (job = j)} />
      {#if hasResults}
        <PocketTable {jobId} />
      {/if}
    {/key}
  {/if}
</main>
