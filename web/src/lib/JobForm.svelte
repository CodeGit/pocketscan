<script lang="ts">
  import { ApiError, createJob } from './api'

  let { onsubmitted }: { onsubmitted: (jobId: number) => void } = $props()

  let text = $state('')
  let error = $state<string | null>(null)
  let busy = $state(false)

  async function submit(event: SubmitEvent) {
    event.preventDefault() // otherwise the browser reloads the page
    const accessions = text.split(/[\s,;]+/).filter(Boolean)
    busy = true
    error = null
    try {
      const job = await createJob(accessions)
      onsubmitted(job.id)
    } catch (e) {
      error = e instanceof ApiError ? e.message : 'Could not reach the server'
    } finally {
      busy = false
    }
  }
</script>

<form onsubmit={submit}>
  <label>
    UniProt accessions (up to 100, separated by spaces, commas or new lines)
    <textarea bind:value={text} rows="3" placeholder="P08100 P0DTC2"></textarea>
  </label>
  <button type="submit" disabled={busy || !text.trim()}>Submit</button>
  {#if error}<p class="error">{error}</p>{/if}
</form>

<style>
  form { display: grid; gap: 0.5rem; margin-bottom: 1.5rem; }
  textarea { font: inherit; }
  .error { color: #c33; }
</style>
