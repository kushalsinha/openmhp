# Other regulator ranges

The descriptor ships with limits for 0-2000 mbar regulators. For a different unit, copy the package
and change two things together:

1. `config.json` `regulators`: the SDK code per channel (1 = 0-200 mbar, 2 = 0-2000 mbar,
   3 = 0-8000 mbar, 4 = -1000..1000 mbar, 5 = -1000..6000 mbar).
2. `descriptor.yaml`: `limits` of every `pressure_setpoint_chN`, set to the lower of the regulator
   range and the pressure rating of whatever the channel feeds.

For 8 bar regulators, also set `approval: confirm` on the pressure settings and on `set_flow`
until the owner has stated the rating of the tubing and cell; 8 bar bursts most chips.
