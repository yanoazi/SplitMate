(() => {
  if (typeof gsap === "undefined") return;
  gsap.registerPlugin(ScrollTrigger);

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const reveals = gsap.utils.toArray(".reveal");

  if (reduce) {
    gsap.set(reveals, { clearProps: "all" });
    return;
  }

  gsap.set(reveals, { autoAlpha: 0, y: 36 });

  const heroItems = gsap.utils.toArray(".hero-stage .reveal");
  const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
  tl.to(heroItems, {
    autoAlpha: 1,
    y: 0,
    duration: 0.85,
    stagger: 0.12,
  }).fromTo(
    ".hero-rule",
    { scaleX: 0 },
    { scaleX: 1, duration: 0.7, ease: "power2.inOut" },
    "-=0.35"
  );

  reveals
    .filter((el) => !el.closest(".hero-stage"))
    .forEach((el) => {
      gsap.to(el, {
        autoAlpha: 1,
        y: 0,
        duration: 0.75,
        ease: "power3.out",
        scrollTrigger: {
          trigger: el,
          start: "top 86%",
          toggleActions: "play none none reverse",
        },
      });
    });

  gsap.utils.toArray(".chapter-dark .feature").forEach((el, i) => {
    gsap.fromTo(
      el,
      { x: i % 2 === 0 ? -24 : 24, autoAlpha: 0 },
      {
        x: 0,
        autoAlpha: 1,
        duration: 0.8,
        ease: "power3.out",
        scrollTrigger: {
          trigger: el,
          start: "top 88%",
          toggleActions: "play none none reverse",
        },
      }
    );
  });
})();
