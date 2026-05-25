**BUILD SUCCESS** ✅

Full output:
```
> yapoc-frontend@0.1.0 build /home/kuweg/Projects/yapoc/app/frontend
> tsc -b && vite build

vite v6.4.2 building for production...
transforming...
✓ 1272 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                     0.39 kB │ gzip:   0.27 kB
dist/assets/index-D90KFB1o.css     65.49 kB │ gzip:  12.90 kB
dist/assets/index-BCQqVO-g.js   1,610.45 kB │ gzip: 504.13 kB

(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 2.74s
```

- **Exit code:** 0
- **Status:** Success
- **Duration:** 2.74s
- **Note:** One non-fatal warning about chunk size (index-BCQqVO-g.js at 1,610 kB). Build completed successfully regardless.