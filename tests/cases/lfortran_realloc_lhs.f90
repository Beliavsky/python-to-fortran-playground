! Reproducer for Windows LFortran 0.66.0 with --realloc-lhs-arrays.
! Expected final vector: 41 51. Failing runs give varying wrong results.
! Initial allocation and resizing passed; repeated runs are important.
implicit none
integer, allocatable :: v(:)
v = [10, 20, 30]
print *, v
print *, size(v)
v = [40, 50]
print *, v
print *, size(v)
v = v + 1
print *, v
end
