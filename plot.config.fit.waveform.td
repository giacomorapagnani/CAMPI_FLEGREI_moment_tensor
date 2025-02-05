--- !grond.PlotConfigCollection
plot_configs:
- !grond.FitsWaveformPlot
  variant: default
  formats:
  - !grond.PDF {}
  size_cm:
  - 9.0
  - 5.0
  nx: 1
  ny: 1
  font_size: 8
  font_size_title: 10
- !grond.MTLocationPlot
  variant: default
  formats:
  - !grond.PDF {}
  font_size: 10.0
  size_cm:
  - 20.0
  - 20.0
  margins_em:
  - 7.0
  - 5.0
  - 7.0
  - 5.0
  separator_em: 1.0
  beachball_type: dc
  normalisation_gamma: 3.0
- !grond.MTDecompositionPlot
  variant: default
  formats:
  - !grond.PDF {}
  font_size: 10.0
  size_cm:
  - 15.0
  - 5.0
  show_reference: true
- !grond.MTFuzzyPlot
  variant: default
  formats:
  - !grond.PDF {}
  font_size: 10.0
  size_cm:
  - 10.0
  - 10.0
