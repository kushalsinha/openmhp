# Standard programs for thermocycler-01

All temperatures in degC, holds in seconds. Lid heater on for every program.

| Polymerase | Denature | Anneal | Extend | Cycles | Final |
|---|---|---|---|---|---|
| Taq | 95 / 30 | 55 to 60 / 30 | 72 / 60 per kb | 30 | 72 / 300 then 4 hold |
| Q5 / Phusion | 98 / 10 | 60 to 65 / 15 | 72 / 30 per kb | 30 to 35 | 72 / 120 then 4 hold |
| KOD | 95 / 20 | 55 to 60 / 10 | 70 / 15 per kb | 30 | 70 / 120 then 4 hold |

Initial denaturation: 95 for 120 (Taq) or 98 for 30 (Q5) before cycling.
Ligation hold: 16 for 3600, then 4 hold. Heat-kill ligase: 65 for 600.
