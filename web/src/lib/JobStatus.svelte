<script lang="ts">
  import { getJob, type Job } from './api'

  let { jobId, onchange }: { jobId: number; onchange?: (job: Job) => void } = $props()

  let job = $state<Job | null>(null)
  let error = $state<string | null>(null)

  $effect(() => {
    const id = jobId
    let stopped = false
    let timer: ReturnType<typeof setTimeout>

    async function poll() {
      try {
        const latest = await getJob(id)
        if (stopped) return
        job = latest
        error = null
        onchange?.(latest)
        if (latest.status === 'pending' || latest.status === 'running') {
          timer = setTimeout(poll, 2000)
        }
      } catch (e) {
        if (stopped) return
        error = e instanceof Error ? e.message : String(e)
        timer = setTimeout(poll, 5000)
      }
    }

    poll()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  })
</script>

{#if error}
  <p class="error">{error}</p>
{/if}

{#if job}
  <h2>Job #{job.id} <span class="badge {job.status}">{job.status}</span></h2>
  <ul>
    {#each job.proteins as protein (protein.accession)}
      <li>
        {protein.accession} <span class="badge {protein.status}">{protein.status}</span>
        {#if protein.error}<span class="reason">{protein.error}</span>{/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul { list-style: none; padding: 0; }
  li { padding: 0.15rem 0; }
  .badge { font-size: 0.8em; padding: 0.1rem 0.5rem; border-radius: 1rem; background: #8884; }
  .succeeded { background: #2a72; color: #2a7; }
  .failed { background: #c332; color: #c33; }
  .running, .pending { background: #fa02; color: #c80; }
  .reason { opacity: 0.7; margin-left: 0.5rem; }
  .error { color: #c33; }
</style>
