-- The blue army's soldiers are 2D characters (friendly, they walk and talk),
-- like the villager, the knight and the wizard. 092 seeded them as decoration.
update object_kinds set category = 'character' where code in ('ally', 'guard');
