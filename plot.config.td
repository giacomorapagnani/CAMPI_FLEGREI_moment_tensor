--- !grond.PlotConfigCollection
plot_configs:
- !grond.HighScoreAcceptancePlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 21.0
  - 14.9
- !grond.BootstrapPlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 21.0
  - 14.9
  show_ticks: false
- !grond.CheckWaveformsPlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 9.0
  - 7.5
  n_random_synthetics: 10
- !grond.ContributionsPlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 21.0
  - 14.9
- !grond.FitsWaveformPlot
  variant: default
  formats:
  - !grond.PNG {}
  size_cm:
  - 9.0
  - 5.0
  nx: 1
  ny: 1
  font_size: 8
  font_size_title: 10
- !grond.FitsWaveformEnsemblePlot
  variant: default
  formats:
  - !grond.PNG {}
  size_cm:
  - 9.0
  - 5.0
  nx: 1
  ny: 1
  color_parameter: misfit
  font_size: 8
  font_size_title: 10
- !grond.HistogramPlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 12.5
  - 7.5
  exclude: []
  include: []
  method: gaussian_kde
  show_reference: true
- !grond.HudsonPlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 17.5
  - 13.125
  beachball_type: dc
  show_reference: true
- !grond.JointparPlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 20.0
  - 20.0
  color_parameter: misfit
  exclude: []
  include: []
  show_ellipses: false
  nsubplots: 6
  show_ticks: false
  show_reference: true
- !grond.MTLocationPlot
  variant: default
  formats:
  - !grond.PNG {}
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
  - !grond.PNG {}
  - !grond.PDF {}
  font_size: 10.0
  size_cm:
  - 15.0
  - 5.0
  show_reference: true
- !grond.MTFuzzyPlot
  variant: default
  formats:
  - !grond.PNG {}
  - !grond.PDF {}
  font_size: 10.0
  size_cm:
  - 10.0
  - 10.0
- !grond.WaveformStationDistribution
  variant: default
  formats:
  - !grond.PNG {}
  size_cm:
  - 16.0
  - 13.0
  font_size: 10
  font_size_labels: 6
- !grond.SequencePlot
  variant: default
  formats:
  - !grond.PNG {}
  font_size: 10.0
  size_cm:
  - 14.0
  - 6.0
  sort_by: iteration
  subplot_layout:
  - 1
  - 1
  marker_size: 1.5
  show_reference: true

