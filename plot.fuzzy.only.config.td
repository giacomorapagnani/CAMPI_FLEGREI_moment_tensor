--- !grond.PlotConfigCollection
plot_configs:
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