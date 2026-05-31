```javascript
/***************************************************************************************************
 *  3‑D POLYHEDRON VISUALISER – A TEACHER'S WALKTHROUGH
 *
 *  This script builds an interactive WebGL scene using the THREE.js library.  The user can
 *  select the level of geometric detail, the type of polyhedron (tetrahedron, hexahedron, …),
 *  and the material applied (normal shading, solid colour, or a texture).  The vertices of the
 *  displayed shape are continuously interpolated with a second, slightly larger shape, creating
 *  a mesmerizing “breathing” animation that can be toggled by clicking near the centre of the
 *  canvas.
 *
 *  Throughout the source you will find extensive commentary.  Jargon is introduced only once
 *  – for instance, **geometry** is defined the first time it appears – and thereafter the same
 *  term is reused without re‑definition.  Wherever a concept is abstract (e.g. the creation of a
 *  *BufferAttribute*), a concrete example is given to cement understanding.
 *
 *  The final block of comments (the “Summary”) recaps the program’s architecture, the data‑flow,
 *  and a minimal example of how to embed the visualiser in an HTML page.
 ***************************************************************************************************/

// -----------------------------------------------------------------------------
// GLOBAL STATE – variables that control the animation and user‑chosen options
// -----------------------------------------------------------------------------
// n – the number of subdivisions (detail) for the chosen geometry.  Subdivisions
//     increase the number of faces, making the shape smoother.  Initially zero.
let n = 0;

// mat – a string identifier for the current material mode (Normal, Color, Texture).
let mat = 0;

// triangles – a helper that records how many triangle groups a particular shape
//            contains; used when computing per‑triangle colour data.
let triangles = 1;

// clique – a Boolean that toggles the interpolation between two shapes.
//          When true the vertices of the small and large polyhedra are blended.
let clique = true;

// -----------------------------------------------------------------------------
// THREE.js CORE COMPONENTS – scene, camera, renderer
// -----------------------------------------------------------------------------
// scene – the container that holds every object we wish to render.  Think of it as a
//         virtual stage.
const scene = new THREE.Scene();

// camera – a *PerspectiveCamera* mimics the way a human eye perceives depth.
//          The first argument (75) is the field‑of‑view in degrees; the next two
//          arguments define the aspect ratio and the near/far clipping planes.
const camera = new THREE.PerspectiveCamera(
	75,                                   // field‑of‑view
	window.innerWidth / window.innerHeight, // aspect ratio
	0.1,                                 // near clipping plane
	1000                                   // far clipping plane
);

// renderer – the engine that draws the scene onto a HTML canvas.  The antialias
//            option smooths jagged edges, improving visual quality.
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement); // inject the canvas into the page

// -----------------------------------------------------------------------------
// GEOMETRY CREATION – two Icosahedron meshes of different radii (1 and 1.5)
// -----------------------------------------------------------------------------
// IcosahedronGeometry – a class that builds a regular 20‑sided polyhedron.
// The second argument, `n`, determines the number of recursive subdivisions.
const geometry = new THREE.IcosahedronGeometry(1, n);
let positions = geometry.getAttribute('position'); // *position* is a BufferAttribute

// A second, slightly larger geometry that will serve as the target for interpolation.
let geometry2 = new THREE.IcosahedronGeometry(1.5, n);
let positions2 = geometry2.getAttribute('position');

// Number of components per vertex attribute:
//   position → 3