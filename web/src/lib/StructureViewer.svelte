<script lang="ts">
  import 'molstar/build/viewer/molstar.css'
  import type { Viewer } from 'molstar/lib/apps/viewer/app'
  import type { Pocket } from './api'

  let { jobId, pocket }: { jobId: number; pocket: Pocket | null } = $props()

  let host = $state<HTMLDivElement>()
  let viewer = $state.raw<Viewer>() // .raw: do not wrap the big Viewer object in a reactive proxy
  let loadingStructure = $state(false)
  let error = $state<string | null>(null)

  const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

  // Mol* hides parts of the scene beyond a far plane and in front of a near plane, which makes
  // atoms vanish when you rotate or zoom. Radius 100 is "show everything"; the near plane
  // cannot be removed, only brought as close to the camera as Mol* allows (0.1).
  const disableClipping = (v: Viewer) =>
    v.plugin.canvas3d?.setProps({ cameraClipping: { radius: 100, far: false, minNear: 0.1 } })

  // "A:207:MET" (chain:number:name) -> a Mol* residue selector, using the author's numbering
  const residueSelector = (residue: string) => {
    const [chain, number] = residue.split(':')
    return { auth_asym_id: chain, auth_seq_id: Number(number) }
  }

  async function buildView(url: string, residues: string[]) {
    // Mol* is large, so it is fetched when first needed and not with the rest of the page.
    const { MVSData } = await import('molstar/lib/extensions/mvs/mvs-data')
    const builder = MVSData.createBuilder()
    const structure = builder.download({ url }).parse({ format: 'mmcif' }).modelStructure()

    structure
      .component({ selector: 'polymer' })
      .representation({ type: 'cartoon' })
      .color({ color: '#b8c4d6' })

    const lining = structure.component({ selector: residues.map(residueSelector) })
    lining.representation({ type: 'ball_and_stick' }).color({ color: '#e8590c' })
    lining.focus()

    return MVSData.toMVSJ(builder.getState())
  }

  // Create the viewer once the div exists; dispose it when the component goes away.
  $effect(() => {
    if (!host) return
    const element = host
    let created: Viewer | undefined
    let cancelled = false
    ;(async () => {
      const { Viewer } = await import('molstar/lib/apps/viewer/app')
      const v = await Viewer.create(element, {
        layoutIsExpanded: false,
        layoutShowControls: false,
        layoutShowSequence: false,
        layoutShowLog: false,
        layoutShowLeftPanel: false,
        viewportShowExpand: false,
      })
      if (cancelled) return v.dispose()
      disableClipping(v)
      created = v
      viewer = v
    })().catch((e) => {
      if (!cancelled) error = message(e)
    })
    return () => {
      cancelled = true
      created?.dispose()
      viewer = undefined
    }
  })

  // Show the selected pocket whenever the viewer is ready or the selection changes.
  let latest = 0
  $effect(() => {
    if (!viewer || !pocket) return
    const v = viewer
    const url = new URL(`/api/jobs/${jobId}/structures/${pocket.accession}`, location.href).href
    const request = ++latest // only the newest selection may update the status
    loadingStructure = true
    error = null
    buildView(url, pocket.residues)
      .then((mvsj) => v.loadMvsData(mvsj, 'mvsj'))
      .then(() => disableClipping(v))
      .catch((e) => {
        if (request === latest) error = message(e)
      })
      .finally(() => {
        if (request === latest) loadingStructure = false
      })
  })

  const status = $derived(
    !viewer && !error ? 'Starting 3D viewer…' : loadingStructure ? 'Loading structure…' : null,
  )
</script>

{#if error}<p class="error">{error}</p>{/if}
<div class="frame">
  <div class="viewer" bind:this={host}></div>
  {#if status}
    <div class="overlay" role="status" aria-live="polite">
      <div class="spinner"></div>
      <span>{status}</span>
    </div>
  {/if}
</div>
{#if !pocket}<p class="hint">Select a pocket (the # button in the table) to view it.</p>{/if}

<style>
  .frame {
    position: relative;
    width: 100%;
    height: 480px;
  }
  .viewer {
    position: relative;
    width: 100%;
    height: 100%; /* Mol* needs an explicit size */
  }
  .overlay {
    position: absolute;
    inset: 0;
    z-index: 10;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    background: #8883;
    backdrop-filter: blur(2px);
    pointer-events: none;
  }
  .spinner {
    width: 2.25rem;
    height: 2.25rem;
    border: 3px solid #8885;
    border-top-color: #e8590c;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      animation-duration: 2.4s;
    }
  }
  .hint {
    opacity: 0.7;
  }
  .error {
    color: #c33;
  }
</style>
